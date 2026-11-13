"""BP-9: Billing pivot sync, reconciliation, and edge-case tests.

Covers reconciliation drift detection, Dodo customer idempotency,
API failure retries, double-webhook idempotency, concurrent debits,
balance-low webhook handling, and isolated Dodo sync task tests.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.billing.factories import CreditWalletFactory, TopupFactory
from apps.billing.models import LedgerKind, WebhookDelivery
from apps.billing.schemas.config import DodoSyncConfig
from apps.billing.services.sync import ensure_dodo_customer, run_nightly_reconciliation
from apps.billing.services.webhooks import _process_event
from apps.billing.tasks.dodo_sync import sync_admin_adjustment, sync_credit_deduction
from apps.core.exceptions import BillingError
from apps.workspaces.factories import WorkspaceFactory
from apps.workspaces.models.workspace import Workspace

_PATCH_DODO_DEDUCTION = "apps.billing.tasks.dodo_sync.dodo_payments.create_credit_deduction"
_PATCH_DODO_ADDITION = "apps.billing.tasks.dodo_sync.dodo_payments.create_credit_addition"
_PATCH_RETRY = "apps.billing.tasks.dodo_sync._schedule_retry"
_PATCH_SENTRY_TASK = "apps.billing.tasks.dodo_sync.sentry_sdk.capture_exception"
_PATCH_EVENT_TASK = "apps.billing.tasks.dodo_sync.record_event"
_PATCH_BALANCE_SYNC = "apps.billing.models.wallet.CreditWallet.sync_balance_from_dodo"
_PATCH_SENTRY_SYNC = "apps.billing.services.sync.sentry_sdk.capture_message"
_PATCH_EVENT_SYNC = "apps.billing.services.sync.record_event"
_PATCH_SYNC_DODO = "apps.billing.services.sync.dodo_payments"

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


class TestReconciliationDetectsDrift:
    """BP-9 item 4: local != Dodo -> mismatch detected + Sentry + PostHog."""

    def test_drift_triggers_sentry_and_posthog(self) -> None:
        wallet = CreditWalletFactory()
        wallet.workspace.dodo_customer_id = "cust_recon"
        wallet.workspace.save(update_fields=("dodo_customer_id",))
        wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="seed_recon")

        with (
            patch(
                _PATCH_BALANCE_SYNC,
                return_value=(Decimal("100.00"), Decimal("75.00"), False),
            ),
            patch(_PATCH_SENTRY_SYNC) as sentry,
            patch(_PATCH_EVENT_SYNC) as event,
        ):
            result = run_nightly_reconciliation()

        assert result == {"checked": 1, "drifted": 1}
        sentry.assert_called_once()
        assert "drift" in sentry.call_args.args[0].lower()
        assert sentry.call_args.kwargs["level"] == "error"
        event.assert_called_once_with(
            "billing_reconciliation_drift",
            distinct_id=str(wallet.workspace_id),
            properties={
                "local": "100.00",
                "remote": "75.00",
                "delta": "25.00",
                "workspace_id": str(wallet.workspace_id),
            },
        )


class TestEnsureDodoCustomerIdempotency:
    """BP-9 item 5: call twice -> same ID, create_customer called once."""

    def test_idempotent_across_two_calls(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=None, billing_email="billing@test.com")

        with patch(_PATCH_SYNC_DODO) as mock_dp:
            mock_dp.create_customer.return_value = SimpleNamespace(customer_id="cus_new_1")
            first = ensure_dodo_customer(ws)

        with patch(_PATCH_SYNC_DODO) as mock_dp:
            second = ensure_dodo_customer(ws)

        assert first == second == "cus_new_1"
        mock_dp.create_customer.assert_not_called()
        ws.refresh_from_db()
        assert ws.dodo_customer_id == "cus_new_1"

    def test_persists_customer_id_on_workspace(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=None)

        with patch(_PATCH_SYNC_DODO) as mock_dp:
            mock_dp.create_customer.return_value = SimpleNamespace(customer_id="cus_persist")
            ensure_dodo_customer(ws)

        reloaded = Workspace.objects.get(pk=ws.pk)
        assert reloaded.dodo_customer_id == "cus_persist"


class TestEdgeCases:
    """BP-9 item 6: API failures, double webhooks, concurrent debits, balance_low."""

    def test_dodo_api_down_sync_retries_local_balance_unaffected(self) -> None:
        wallet = CreditWalletFactory()
        wallet.workspace.dodo_customer_id = "cust_retry_edge"
        wallet.workspace.save(update_fields=("dodo_customer_id",))
        wallet.record_dodo_credit_grant(Decimal("60.00"), dodo_payment_id="seed_edge")
        wallet.debit(Decimal("15.00"), reason="run_a", reference="run-a")

        with (
            patch(_PATCH_DODO_DEDUCTION, side_effect=RuntimeError("timeout")),
            patch(_PATCH_RETRY) as mock_retry,
        ):
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="15.00",
                reference="run-a",
                reason="run_a",
                attempt=1,
            )
        mock_retry.assert_called_once()

        with (
            patch(_PATCH_DODO_DEDUCTION, side_effect=RuntimeError("still down")),
            patch(_PATCH_RETRY) as mock_retry2,
        ):
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="15.00",
                reference="run-a",
                reason="run_a",
                attempt=2,
            )
        mock_retry2.assert_called_once()

        with (
            patch(_PATCH_DODO_DEDUCTION, side_effect=RuntimeError("permanent")),
            patch(_PATCH_SENTRY_TASK) as sentry,
            patch(_PATCH_EVENT_TASK) as event,
        ):
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="15.00",
                reference="run-a",
                reason="run_a",
                attempt=DodoSyncConfig().max_attempts,
            )
        sentry.assert_called_once()
        event.assert_called_once()

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("45.0000")

    def test_double_payment_succeeded_webhook_idempotent(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("100.00"))

        event = _make_payment_event(
            payment_id="pay_double",
            metadata={"reference": str(topup.pk)},
        )
        first = _process_event(event, "{}", event_id="whmsg_double_1")
        second = _process_event(event, "{}", event_id="whmsg_double_1")

        assert first is True
        assert second is False
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("100.0000")
        assert wallet.entries.filter(kind=LedgerKind.TOPUP).count() == 1
        assert WebhookDelivery.objects.filter(event_id="whmsg_double_1").count() == 1

    def test_concurrent_debits_serialized_no_oversell(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed_conc")

        wallet.debit(Decimal("30.00"), reason="run_1", reference="run-1")

        with pytest.raises(BillingError, match="Insufficient"):
            wallet.debit(Decimal("30.00"), reason="run_2", reference="run-2")

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("20.0000")
        assert wallet.entries.filter(kind=LedgerKind.RUN_DEBIT).count() == 1

    def test_admin_adjustment_and_concurrent_debit_independent(self) -> None:
        wallet = CreditWalletFactory()
        wallet.workspace.dodo_customer_id = "cust_adj"
        wallet.workspace.save(update_fields=("dodo_customer_id",))
        wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="seed_adj")

        wallet.debit(Decimal("25.00"), reason="run_x", reference="run-x")
        wallet.post_adjustment(Decimal("10.00"), note="Goodwill credit", reference="admin-1")

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("85.0000")

        with patch("apps.billing.tasks.dodo_sync.dodo_payments.create_credit_addition") as mock_add:
            sync_admin_adjustment.call(
                wallet_id=wallet.pk,
                delta_usd="10.00",
                note="Goodwill credit",
                reference="admin-1",
            )
        mock_add.assert_called_once()

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("85.0000")

    def test_credit_balance_low_webhook_emits_event_no_balance_mutation(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id="cust_low_bal")
        wallet = CreditWalletFactory(workspace=ws)
        wallet.record_dodo_credit_grant(Decimal("5.00"), dodo_payment_id="seed_low")

        event = SimpleNamespace(
            type="credit.balance_low",
            business_id="biz_1",
            data=SimpleNamespace(
                customer_id="cust_low_bal",
                available_balance=500,
                threshold_percent=20,
            ),
        )
        with patch("apps.billing.services.webhooks.record_event") as mock_event:
            result = _process_event(event, "{}", event_id="whmsg_low_bal")

        assert result is True
        mock_event.assert_called()
        event_calls = [c for c in mock_event.call_args_list if c[0][0] == "credit_balance_low"]
        assert len(event_calls) == 1
        props = event_calls[0][1]["properties"]
        assert props["workspace_id"] == ws.pk
        assert props["available"] == "500"
        assert props["threshold"] == "20"

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("5.0000")


# --- Isolated sync task tests (formerly test_dodo_sync.py) ---


def _wallet_with_customer():
    wallet = CreditWalletFactory()
    wallet.workspace.dodo_customer_id = "cust_test_123"
    wallet.workspace.save(update_fields=("dodo_customer_id",))
    return wallet


class TestSyncCreditDeductionIsolated:
    def test_happy_path(self) -> None:
        wallet = _wallet_with_customer()
        with patch(_PATCH_DODO_DEDUCTION) as mock_deduct:
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="5.50",
                reference="run-123",
                reason="run_completion",
            )
        mock_deduct.assert_called_once_with(
            customer_id="cust_test_123",
            entitlement_id="",
            amount=550,
            description="run_completion [run-123]",
        )

    def test_retries_on_failure(self) -> None:
        wallet = _wallet_with_customer()
        with (
            patch(_PATCH_DODO_DEDUCTION, side_effect=RuntimeError("timeout")),
            patch(_PATCH_RETRY) as mock_retry,
        ):
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="10.00",
                reference="run-456",
                reason="run_debit",
                attempt=1,
            )
        mock_retry.assert_called_once()
        call_kwargs = mock_retry.call_args[1]
        assert call_kwargs["attempt"] == 2
        assert call_kwargs["wallet_id"] == wallet.pk

    def test_final_failure_alerts(self) -> None:
        wallet = _wallet_with_customer()
        with (
            patch(_PATCH_DODO_DEDUCTION, side_effect=RuntimeError("permanent")),
            patch(_PATCH_SENTRY_TASK) as mock_sentry,
            patch(_PATCH_EVENT_TASK) as mock_event,
        ):
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="25.00",
                reference="run-789",
                reason="run_cost",
                attempt=DodoSyncConfig().max_attempts,
            )
        mock_sentry.assert_called_once()
        mock_event.assert_called_once()
        assert mock_event.call_args[0][0] == "billing_dodo_sync_failed"

    def test_no_customer_id_alerts_on_final_attempt(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_SENTRY_TASK) as mock_sentry,
            patch(_PATCH_EVENT_TASK) as mock_event,
        ):
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="5.00",
                reference="run-x",
                reason="run_cost",
                attempt=DodoSyncConfig().max_attempts,
            )
        mock_sentry.assert_called_once()
        mock_event.assert_called_once()

    def test_no_customer_id_retries_before_final(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_RETRY) as mock_retry,
            patch(_PATCH_SENTRY_TASK) as mock_sentry,
        ):
            sync_credit_deduction.call(
                wallet_id=wallet.pk,
                amount_usd="5.00",
                reference="run-x",
                reason="run_cost",
                attempt=1,
            )
        mock_retry.assert_called_once()
        mock_sentry.assert_not_called()


class TestSyncAdminAdjustmentIsolated:
    def test_positive_adjustment_calls_addition(self) -> None:
        wallet = _wallet_with_customer()
        with patch(_PATCH_DODO_ADDITION) as mock_add:
            sync_admin_adjustment.call(
                wallet_id=wallet.pk,
                delta_usd="15.00",
                note="Goodwill credit",
                reference="admin-1",
            )
        mock_add.assert_called_once_with(
            customer_id="cust_test_123",
            entitlement_id="",
            amount=1500,
            description="Goodwill credit",
        )

    def test_negative_adjustment_calls_deduction(self) -> None:
        wallet = _wallet_with_customer()
        with patch(_PATCH_DODO_DEDUCTION) as mock_deduct:
            sync_admin_adjustment.call(
                wallet_id=wallet.pk,
                delta_usd="-8.50",
                note="Correction for overcharge",
                reference="admin-2",
            )
        mock_deduct.assert_called_once_with(
            customer_id="cust_test_123",
            entitlement_id="",
            amount=850,
            description="Correction for overcharge",
        )

    def test_retries_on_failure(self) -> None:
        wallet = _wallet_with_customer()
        with (
            patch(_PATCH_DODO_ADDITION, side_effect=RuntimeError("network")),
            patch(_PATCH_RETRY) as mock_retry,
        ):
            sync_admin_adjustment.call(
                wallet_id=wallet.pk,
                delta_usd="20.00",
                note="Grant",
                reference="admin-3",
                attempt=2,
            )
        mock_retry.assert_called_once()
        assert mock_retry.call_args[1]["attempt"] == 3

    def test_final_failure_alerts(self) -> None:
        wallet = _wallet_with_customer()
        with (
            patch(_PATCH_DODO_ADDITION, side_effect=RuntimeError("down")),
            patch(_PATCH_SENTRY_TASK) as mock_sentry,
            patch(_PATCH_EVENT_TASK) as mock_event,
        ):
            sync_admin_adjustment.call(
                wallet_id=wallet.pk,
                delta_usd="10.00",
                note="Promo",
                reference="admin-4",
                attempt=DodoSyncConfig().max_attempts,
            )
        mock_sentry.assert_called_once()
        mock_event.assert_called_once()
        assert mock_event.call_args[0][0] == "billing_dodo_adjustment_sync_failed"
