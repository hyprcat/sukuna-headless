"""Tests for Dodo sync services: customer lifecycle + nightly reconciliation."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.billing.factories import CreditWalletFactory
from apps.billing.services.sync import (
    ensure_dodo_customer,
    run_nightly_reconciliation,
    sync_customer_email,
)
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db

_CUSTOMER_ID = "cus_test_123"
_PATCH_DODO = "apps.billing.services.sync.dodo_payments"
_PATCH_BALANCE_SYNC = "apps.billing.models.wallet.CreditWallet.sync_balance_from_dodo"
_PATCH_SENTRY = "apps.billing.services.sync.sentry_sdk.capture_message"
_PATCH_EVENT = "apps.billing.services.sync.record_event"


def _mock_customer(customer_id: str = _CUSTOMER_ID) -> SimpleNamespace:
    return SimpleNamespace(customer_id=customer_id)


# ---------------------------------------------------------------------------
# Customer lifecycle
# ---------------------------------------------------------------------------


class TestEnsureDodoCustomer:
    def test_returns_existing_customer_id_without_api_call(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=_CUSTOMER_ID)
        with patch(_PATCH_DODO) as mock_dp:
            result = ensure_dodo_customer(ws)
        assert result == _CUSTOMER_ID
        mock_dp.create_customer.assert_not_called()

    def test_creates_customer_and_stores_id(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=None, billing_email="billing@example.com")
        with patch(_PATCH_DODO) as mock_dp:
            mock_dp.create_customer.return_value = _mock_customer()
            result = ensure_dodo_customer(ws)

        assert result == _CUSTOMER_ID
        assert ws.dodo_customer_id == _CUSTOMER_ID
        ws.refresh_from_db()
        assert ws.dodo_customer_id == _CUSTOMER_ID
        mock_dp.create_customer.assert_called_once_with(name=ws.name, email="billing@example.com")

    def test_uses_owner_email_when_billing_email_empty(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=None, billing_email="")
        with patch(_PATCH_DODO) as mock_dp:
            mock_dp.create_customer.return_value = _mock_customer()
            ensure_dodo_customer(ws)

        mock_dp.create_customer.assert_called_once_with(name=ws.name, email=ws.owner.email)

    def test_idempotent_concurrent_calls(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=None)
        with patch(_PATCH_DODO) as mock_dp:
            mock_dp.create_customer.return_value = _mock_customer()
            first = ensure_dodo_customer(ws)

        with patch(_PATCH_DODO) as mock_dp:
            second = ensure_dodo_customer(ws)

        assert first == second == _CUSTOMER_ID
        mock_dp.create_customer.assert_not_called()

    def test_race_safe_second_caller_sees_first_result(self) -> None:
        from apps.workspaces.models.workspace import Workspace  # noqa: PLC0415

        ws = WorkspaceFactory(dodo_customer_id=None)
        with patch(_PATCH_DODO) as mock_dp:
            mock_dp.create_customer.return_value = _mock_customer()
            ensure_dodo_customer(ws)

        ws2 = Workspace.objects.get(pk=ws.pk)
        assert ws2.dodo_customer_id == _CUSTOMER_ID

        with patch(_PATCH_DODO) as mock_dp:
            result = ensure_dodo_customer(ws2)

        assert result == _CUSTOMER_ID
        mock_dp.create_customer.assert_not_called()


class TestSyncCustomerEmail:
    def test_syncs_billing_email_to_dodo(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=_CUSTOMER_ID, billing_email="new@example.com")
        with patch(_PATCH_DODO) as mock_dp:
            sync_customer_email(ws.pk)

        mock_dp.update_customer.assert_called_once_with(_CUSTOMER_ID, email="new@example.com")

    def test_uses_owner_email_when_billing_email_empty(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=_CUSTOMER_ID, billing_email="")
        with patch(_PATCH_DODO) as mock_dp:
            sync_customer_email(ws.pk)

        mock_dp.update_customer.assert_called_once_with(_CUSTOMER_ID, email=ws.owner.email)

    def test_skips_when_no_dodo_customer(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=None)
        with patch(_PATCH_DODO) as mock_dp:
            sync_customer_email(ws.pk)

        mock_dp.update_customer.assert_not_called()


class TestEmailSyncTaskTrigger:
    def test_update_settings_enqueues_sync_on_email_change(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=_CUSTOMER_ID, billing_email="old@example.com")
        with patch("apps.billing.tasks.reconcile.sync_dodo_customer_email") as mock_task:
            ws.update_settings(billing_email="new@example.com")

        mock_task.enqueue.assert_called_once_with(ws.pk)

    def test_update_settings_skips_sync_when_email_unchanged(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=_CUSTOMER_ID, billing_email="same@example.com")
        with patch("apps.billing.tasks.reconcile.sync_dodo_customer_email") as mock_task:
            ws.update_settings(billing_email="same@example.com")

        mock_task.enqueue.assert_not_called()

    def test_update_settings_skips_sync_when_no_dodo_customer(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=None, billing_email="old@example.com")
        with patch("apps.billing.tasks.reconcile.sync_dodo_customer_email") as mock_task:
            ws.update_settings(billing_email="new@example.com")

        mock_task.enqueue.assert_not_called()

    def test_update_settings_name_only_no_sync(self) -> None:
        ws = WorkspaceFactory(dodo_customer_id=_CUSTOMER_ID, billing_email="x@example.com")
        with patch("apps.billing.tasks.reconcile.sync_dodo_customer_email") as mock_task:
            ws.update_settings(name="New Name")

        mock_task.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Nightly reconciliation
# ---------------------------------------------------------------------------


def _wallet_with_activity(
    balance: str = "100.00",
    customer_id: str = "cust_test",
) -> CreditWalletFactory:
    wallet = CreditWalletFactory()
    wallet.workspace.dodo_customer_id = customer_id
    wallet.workspace.save(update_fields=["dodo_customer_id"])
    wallet.record_dodo_credit_grant(Decimal(balance), dodo_payment_id="seed")
    return wallet


class TestReconciliation:
    def test_clean_no_drift(self) -> None:
        _wallet_with_activity()
        with (
            patch(_PATCH_BALANCE_SYNC, return_value=(Decimal("100.00"), Decimal("100.00"), True)),
            patch(_PATCH_SENTRY) as sentry,
            patch(_PATCH_EVENT) as event,
        ):
            result = run_nightly_reconciliation()
        assert result == {"checked": 1, "drifted": 0}
        sentry.assert_not_called()
        event.assert_not_called()

    def test_drift_detected(self) -> None:
        wallet = _wallet_with_activity()
        with (
            patch(_PATCH_BALANCE_SYNC, return_value=(Decimal("100.00"), Decimal("80.00"), False)),
            patch(_PATCH_SENTRY) as sentry,
            patch(_PATCH_EVENT) as event,
        ):
            result = run_nightly_reconciliation()
        assert result == {"checked": 1, "drifted": 1}
        sentry.assert_called_once()
        assert "drift" in sentry.call_args.args[0].lower()
        event.assert_called_once()
        props = event.call_args.kwargs["properties"]
        assert props["local"] == "100.00"
        assert props["remote"] == "80.00"
        assert props["workspace_id"] == str(wallet.workspace_id)

    def test_no_activity_skipped(self) -> None:
        wallet = CreditWalletFactory()
        wallet.workspace.dodo_customer_id = "cust_idle"
        wallet.workspace.save(update_fields=["dodo_customer_id"])
        with (
            patch(_PATCH_BALANCE_SYNC) as sync_mock,
            patch(_PATCH_SENTRY) as sentry,
        ):
            result = run_nightly_reconciliation()
        assert result == {"checked": 0, "drifted": 0}
        sync_mock.assert_not_called()
        sentry.assert_not_called()

    def test_no_dodo_customer_skipped(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")
        with (
            patch(_PATCH_BALANCE_SYNC) as sync_mock,
            patch(_PATCH_SENTRY) as sentry,
        ):
            result = run_nightly_reconciliation()
        assert result == {"checked": 0, "drifted": 0}
        sync_mock.assert_not_called()
        sentry.assert_not_called()

    def test_multiple_wallets(self) -> None:
        _wallet_with_activity(balance="50.00", customer_id="cust_a")
        _wallet_with_activity(balance="100.00", customer_id="cust_b")
        sync_results = iter(
            [
                (Decimal("50.00"), Decimal("50.00"), True),
                (Decimal("100.00"), Decimal("80.00"), False),
            ]
        )
        with (
            patch(_PATCH_BALANCE_SYNC, side_effect=lambda: next(sync_results)),
            patch(_PATCH_SENTRY) as sentry,
            patch(_PATCH_EVENT) as event,
        ):
            result = run_nightly_reconciliation()
        assert result == {"checked": 2, "drifted": 1}
        sentry.assert_called_once()
        event.assert_called_once()

    def test_sentry_level_is_error(self) -> None:
        _wallet_with_activity()
        with (
            patch(_PATCH_BALANCE_SYNC, return_value=(Decimal("100.00"), Decimal("0.00"), False)),
            patch(_PATCH_SENTRY) as sentry,
            patch(_PATCH_EVENT),
        ):
            run_nightly_reconciliation()
        assert sentry.call_args.kwargs["level"] == "error"

    def test_empty_database(self) -> None:
        with (
            patch(_PATCH_SENTRY) as sentry,
        ):
            result = run_nightly_reconciliation()
        assert result == {"checked": 0, "drifted": 0}
        sentry.assert_not_called()

    def test_drift_event_distinct_id(self) -> None:
        wallet = _wallet_with_activity()
        with (
            patch(_PATCH_BALANCE_SYNC, return_value=(Decimal("10.00"), Decimal("5.00"), False)),
            patch(_PATCH_SENTRY),
            patch(_PATCH_EVENT) as event,
        ):
            run_nightly_reconciliation()
        assert event.call_args.kwargs["distinct_id"] == str(wallet.workspace_id)

    def test_sync_exception_propagates(self) -> None:
        _wallet_with_activity()
        with (
            patch(_PATCH_BALANCE_SYNC, side_effect=Exception("Dodo API down")),
            pytest.raises(Exception, match="Dodo API down"),
        ):
            run_nightly_reconciliation()
