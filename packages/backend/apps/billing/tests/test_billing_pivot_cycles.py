"""BP-9: End-to-end billing pivot cycle tests (lifecycle flows).

Verifies the full lifecycle flows introduced by the Dodo credit-based
billing pivot (BP-1 through BP-8). Covers topup, debit, and refund cycles.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.billing.factories import CreditWalletFactory, TopupFactory
from apps.billing.models import LedgerKind, TopupStatus
from apps.billing.schemas.config import DodoSyncConfig
from apps.billing.services.dodo import create_topup, refund_topup
from apps.billing.services.webhooks import _process_event
from apps.billing.tasks.dodo_sync import sync_credit_deduction

_PATCH_LINK = "apps.billing.services.dodo.dodo_payments.create_payment_link"
_PATCH_EVENT = "apps.billing.services.dodo.record_event"
_PATCH_ENSURE = "apps.billing.services.dodo.ensure_dodo_customer"

pytestmark = pytest.mark.django_db


def _make_payment_event(
    payment_id: str = "pay_123",
    event_type: str = "payment.succeeded",
    metadata: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        type=event_type,
        business_id="biz_1",
        data=SimpleNamespace(
            payment_id=payment_id,
            metadata=metadata or {},
            status=None,
        ),
    )


def _make_refund_event(
    refund_id: str = "ref_123",
    payment_id: str = "pay_123",
) -> SimpleNamespace:
    return SimpleNamespace(
        type="refund.succeeded",
        business_id="biz_1",
        data=SimpleNamespace(refund_id=refund_id, payment_id=payment_id),
    )


class TestTopupCycle:
    """BP-9 item 1: create payment -> webhook -> record_dodo_credit_grant -> correct balance."""

    def test_full_topup_lifecycle(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://checkout.dodo.com/s1"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_cycle"),
        ):
            topup, url = create_topup(wallet, Decimal("50.00"), "cycle-key-1")

        assert topup.status == TopupStatus.PENDING
        assert url == "https://checkout.dodo.com/s1"
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("0")

        event = _make_payment_event(
            payment_id="pay_cycle_1",
            metadata={"reference": str(topup.pk)},
        )
        result = _process_event(event, '{"webhook": "body"}', event_id="whmsg_cycle_1")

        assert result is True
        topup.refresh_from_db()
        assert topup.status == TopupStatus.SUCCEEDED
        assert topup.dodo_payment_id == "pay_cycle_1"
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")

        entry = wallet.entries.get(kind=LedgerKind.TOPUP)
        assert entry.delta_usd == Decimal("50.0000")
        assert entry.reference == "pay_cycle_1"

    def test_topup_cycle_with_multiple_amounts(self) -> None:
        wallet = CreditWalletFactory()
        for i, amount in enumerate([Decimal("20.00"), Decimal("100.00")], start=1):
            with (
                patch(_PATCH_LINK, return_value=f"https://dodo.com/s{i}"),
                patch(_PATCH_EVENT),
                patch(_PATCH_ENSURE, return_value="cust_multi"),
            ):
                topup, _ = create_topup(wallet, amount, f"multi-key-{i}")

            event = _make_payment_event(
                payment_id=f"pay_multi_{i}",
                metadata={"reference": str(topup.pk)},
            )
            _process_event(event, "{}", event_id=f"whmsg_multi_{i}")

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("120.0000")
        assert wallet.entries.filter(kind=LedgerKind.TOPUP).count() == 2


class TestDebitCycle:
    """BP-9 item 2: wallet.debit -> local balance decremented -> sync task enqueued."""

    def test_debit_decrements_balance_and_enqueues_sync(self) -> None:
        wallet = CreditWalletFactory()
        wallet.workspace.dodo_customer_id = "cust_debit"
        wallet.workspace.save(update_fields=("dodo_customer_id",))
        wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="seed_debit")

        wallet.debit(Decimal("35.50"), reason="run_completion", reference="run-abc")

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("64.5000")
        entry = wallet.entries.get(kind=LedgerKind.RUN_DEBIT)
        assert entry.delta_usd == Decimal("-35.5000")
        assert entry.reference == "run-abc"

    def test_sync_task_propagates_deduction_to_dodo(self) -> None:
        wallet = CreditWalletFactory()
        wallet.workspace.dodo_customer_id = "cust_sync_debit"
        wallet.workspace.save(update_fields=("dodo_customer_id",))

        _patch = "apps.billing.tasks.dodo_sync.dodo_payments.create_credit_deduction"
        with patch(_patch) as mock_deduct:
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="35.50",
                reference="run-abc",
                reason="run_completion",
            )

        mock_deduct.assert_called_once_with(
            customer_id="cust_sync_debit",
            entitlement_id="",
            amount=3550,
            description="run_completion [run-abc]",
        )

    def test_local_balance_unaffected_by_sync_failure(self) -> None:
        wallet = CreditWalletFactory()
        wallet.workspace.dodo_customer_id = "cust_fail"
        wallet.workspace.save(update_fields=("dodo_customer_id",))
        wallet.record_dodo_credit_grant(Decimal("80.00"), dodo_payment_id="seed_fail")
        wallet.debit(Decimal("20.00"), reason="run_cost", reference="run-fail")

        _deduct = "apps.billing.tasks.dodo_sync.dodo_payments.create_credit_deduction"
        with (
            patch(_deduct, side_effect=RuntimeError("API down")),
            patch("apps.billing.tasks.dodo_sync.sentry_sdk.capture_exception"),
            patch("apps.billing.tasks.dodo_sync.record_event"),
        ):
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="20.00",
                reference="run-fail",
                reason="run_cost",
                attempt=DodoSyncConfig().max_attempts,
            )

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("60.0000")


class TestRefundCycle:
    """BP-9 item 3: refund_topup -> Dodo called, no local entry -> webhook -> ledger + balance."""

    def _create_refundable_topup(self, wallet):
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed_ref")
        return TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_ref_cycle",
        )

    def test_refund_request_does_not_change_local_balance(self) -> None:
        wallet = CreditWalletFactory()
        topup = self._create_refundable_topup(wallet)

        with (
            patch("apps.billing.services.dodo.dodo_payments.refund_full_payment") as mock_refund,
            patch(_PATCH_EVENT),
        ):
            mock_refund.return_value = SimpleNamespace(refund_id="ref_cycle", status="pending")
            refund_topup(topup, reason="customer request")

        topup.refresh_from_db()
        assert topup.status == TopupStatus.REFUND_REQUESTED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")
        assert not wallet.entries.filter(kind=LedgerKind.REFUND).exists()

    def test_refund_webhook_debits_balance_and_writes_ledger(self) -> None:
        wallet = CreditWalletFactory()
        self._create_refundable_topup(wallet)
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.REFUND_REQUESTED,
            dodo_payment_id="pay_ref_wh",
            refund_reason="customer request",
        )
        refund_event = _make_refund_event(refund_id="ref_wh", payment_id="pay_ref_wh")
        _process_event(refund_event, "{}", event_id="whmsg_refund_wh")

        topup.refresh_from_db()
        assert topup.status == TopupStatus.REFUNDED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("0")
        entry = wallet.entries.get(kind=LedgerKind.REFUND)
        assert entry.delta_usd == Decimal("-50.0000")
        assert entry.reference == str(topup.pk)
        assert entry.note == "customer request"
