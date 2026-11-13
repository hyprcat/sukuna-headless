"""Edge-case tests: partial refund, topup-signed-but-never-paid, and currency constraints."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction

from apps.billing.factories import CreditWalletFactory, TopupFactory
from apps.billing.models import LedgerEntry, LedgerKind, Topup, TopupStatus
from apps.billing.schemas import BillingFormat
from apps.billing.services.dodo import create_topup, refund_topup
from apps.billing.services.webhooks import _process_event
from apps.core.exceptions import Conflict

_PATCH_LINK = "apps.billing.services.dodo.dodo_payments.create_payment_link"
_PATCH_REFUND = "apps.billing.services.dodo.dodo_payments.refund_full_payment"
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
        ),
    )


class TestRefundRequestEdgeCases:
    def test_refund_request_after_partial_debit_does_not_change_balance(self) -> None:
        """Wallet has $100, debit $30, refund request — balance stays $70."""
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("100.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_partial",
        )
        wallet.debit(Decimal("30.00"), reason="run_complete", reference="run_1")

        with patch(_PATCH_REFUND), patch(_PATCH_EVENT):
            result = refund_topup(topup, reason="customer request")

        assert result.status == TopupStatus.REFUND_REQUESTED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("70.0000")

    def test_refund_request_does_not_write_ledger_entry(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_exact",
        )

        with patch(_PATCH_REFUND), patch(_PATCH_EVENT):
            refund_topup(topup, reason="exact balance refund")

        assert not wallet.entries.filter(kind=LedgerKind.REFUND).exists()
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")

    def test_refund_request_after_multiple_topups_and_debits(self) -> None:
        """Complex ledger: multiple topups/debits, refund request doesn't touch balance."""
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="topup-1")
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="topup-2")
        wallet.debit(Decimal("25.00"), reason="run_1", reference="run_1")
        wallet.debit(Decimal("10.00"), reason="run_2", reference="run_2")

        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_multi_refund",
        )

        with patch(_PATCH_REFUND), patch(_PATCH_EVENT):
            result = refund_topup(topup, reason="partial ledger refund")

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("115.0000")
        assert result.status == TopupStatus.REFUND_REQUESTED
        assert not wallet.entries.filter(kind=LedgerKind.REFUND).exists()

    def test_double_refund_request_fails_before_provider_call(self) -> None:
        """Requesting refund twice never reaches Dodo again."""
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_double_ref",
        )

        with patch(_PATCH_REFUND), patch(_PATCH_EVENT):
            refund_topup(topup, reason="first refund")

        with (
            pytest.raises(Conflict, match="already requested"),
            patch(_PATCH_REFUND) as mock_refund,
        ):
            refund_topup(topup, reason="second refund")

        mock_refund.assert_not_called()


class TestTopupNeverPaid:
    def test_pending_topup_does_not_affect_balance(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_x"),
        ):
            topup, _ = create_topup(wallet, Decimal("100.00"), "abandoned-key")

        assert topup.status == TopupStatus.PENDING
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("0")
        assert wallet.entries.count() == 0

    def test_pending_topup_not_included_in_available(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="real")
        TopupFactory(wallet=wallet, amount_usd=Decimal("500.00"))

        assert wallet.available() == Decimal("20.0000")

    def test_pending_topup_cannot_be_refunded(self) -> None:
        topup = TopupFactory(status=TopupStatus.PENDING)
        with pytest.raises(Conflict, match="Only succeeded"):
            refund_topup(topup, reason="never paid")

    def test_stale_pending_key_not_reusable_after_failure(self) -> None:
        """After Dodo marks a topup as failed, the key is stuck."""
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_x"),
        ):
            topup, _ = create_topup(wallet, Decimal("20.00"), "stale-key")

        topup.fail()

        with pytest.raises(Conflict, match="already settled"):
            create_topup(wallet, Decimal("20.00"), "stale-key")

    def test_multiple_abandoned_topups_coexist(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_x"),
        ):
            t1, _ = create_topup(wallet, Decimal("20.00"), "abandon-1")
            t2, _ = create_topup(wallet, Decimal("50.00"), "abandon-2")
            t3, _ = create_topup(wallet, Decimal("100.00"), "abandon-3")

        assert t1.pk != t2.pk != t3.pk
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("0")
        assert wallet.entries.count() == 0

    def test_settling_one_pending_leaves_others_pending(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_x"),
        ):
            t1, _ = create_topup(wallet, Decimal("20.00"), "multi-1")
            t2, _ = create_topup(wallet, Decimal("50.00"), "multi-2")

        event = _make_payment_event(
            payment_id="pay_one",
            event_type="payment.succeeded",
            metadata={"reference": str(t1.pk)},
        )
        _process_event(event, "{}", event_id="whmsg_one")

        t1.refresh_from_db()
        t2.refresh_from_db()
        assert t1.status == TopupStatus.SUCCEEDED
        assert t2.status == TopupStatus.PENDING
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("20.0000")


class TestCurrencyConstraints:
    def test_billing_money_rows_store_currency_codes(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet)
        entry = wallet.record_dodo_credit_grant(
            Decimal("20.00"), dodo_payment_id="dodo_pay_currency"
        )
        assert wallet.currency == BillingFormat().currency
        assert topup.currency == BillingFormat().currency
        assert entry.currency == BillingFormat().currency

    def test_wallet_currency_constraint_blocks_non_usd_writes(self) -> None:
        wallet = CreditWalletFactory()
        wallet.currency = "EUR"
        with pytest.raises(IntegrityError), transaction.atomic():
            wallet.save(update_fields=("currency", "updated_at"))

    def test_topup_rejects_non_usd_currency_at_model_boundary(self) -> None:
        wallet = CreditWalletFactory()
        topup = Topup(
            wallet=wallet,
            amount_usd=Decimal("20.00"),
            currency="EUR",
            idempotency_key="eur-topup",
        )
        with pytest.raises(Conflict, match="currency"):
            topup.save()

    def test_ledger_entry_rejects_non_usd_currency_at_model_boundary(self) -> None:
        wallet = CreditWalletFactory()
        entry = LedgerEntry(
            wallet=wallet,
            delta_usd=Decimal("20.00"),
            currency="EUR",
            kind=LedgerKind.TOPUP,
            reference="eur-ledger",
        )
        with pytest.raises(Conflict, match="currency"):
            entry.save()
