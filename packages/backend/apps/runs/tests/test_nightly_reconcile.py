from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from apps.billing.factories import BillingHoldFactory, LedgerEntryFactory
from apps.billing.models.hold import HoldStatus
from apps.billing.models.ledger import LedgerKind
from apps.runs.factories import RunFactory, SandboxInstanceFactory
from apps.runs.tasks.nightly_reconcile import nightly_reconciliation

pytestmark = pytest.mark.django_db(transaction=True)


class TestNightlyReconciliationDrift:
    @patch("apps.runs.tasks.nightly_reconcile.record_event")
    @patch("apps.runs.tasks.nightly_reconcile.sentry_sdk")
    @patch(
        "apps.runs.tasks.nightly_reconcile.e2b.list_sandbox_states",
        new_callable=AsyncMock,
    )
    def test_drift_detected_and_alerted(self, mock_e2b, mock_sentry, mock_record):
        # Terminal run with an ACTIVE hold → hold_state_drift = 1
        run = RunFactory(finished=True)
        BillingHoldFactory(run=run, wallet__workspace=run.workspace, status=HoldStatus.ACTIVE)
        # Match e2b count to avoid sandbox_drift
        mock_e2b.return_value = {}

        result = nightly_reconciliation()

        assert result["hold_state_drift"] >= 1
        mock_sentry.capture_message.assert_called_once_with(
            "nightly_reconciliation drift detected", level="warning"
        )
        mock_record.assert_called_once_with(
            "nightly_reconciliation_drift",
            distinct_id="system",
            properties=result,
        )

    @patch("apps.runs.tasks.nightly_reconcile.record_event")
    @patch("apps.runs.tasks.nightly_reconcile.sentry_sdk")
    @patch(
        "apps.runs.tasks.nightly_reconcile.e2b.list_sandbox_states",
        new_callable=AsyncMock,
    )
    def test_sandbox_count_mismatch_alerts(self, mock_e2b, mock_sentry, mock_record):
        # One live sandbox in our DB, zero in E2B → sandbox_drift = 1
        SandboxInstanceFactory(running=True)
        mock_e2b.return_value = {}

        result = nightly_reconciliation()

        assert result["sandbox_drift"] >= 1
        mock_sentry.capture_message.assert_called_once()
        mock_record.assert_called_once()


class TestNightlyReconciliationClean:
    @patch("apps.runs.tasks.nightly_reconcile.record_event")
    @patch("apps.runs.tasks.nightly_reconcile.sentry_sdk")
    @patch(
        "apps.runs.tasks.nightly_reconcile.e2b.list_sandbox_states",
        new_callable=AsyncMock,
    )
    def test_clean_state_no_alerts(self, mock_e2b, mock_sentry, mock_record):
        # Settled hold with a matching ledger debit — no ledger drift
        run = RunFactory(finished=True)
        hold = BillingHoldFactory(
            run=run,
            wallet__workspace=run.workspace,
            status=HoldStatus.SETTLED,
            amount_consumed_usd=Decimal("5.00"),
            settled_at=run.finished_at,
        )
        wallet = hold.wallet
        # Create the matching run_debit ledger entry (delta negative = debit)
        LedgerEntryFactory(
            wallet=wallet,
            kind=LedgerKind.RUN_DEBIT,
            reference=str(run.run_uid),
            delta_usd=Decimal("-5.00"),
        )
        # Terminal run has a SETTLED (not active) hold — no hold_state_drift
        # No live sandboxes in our DB; mock e2b returns empty too
        mock_e2b.return_value = {}
        # run has last_projected_sequence=0 by default — no callback_drift window

        result = nightly_reconciliation()

        assert result == {
            "ledger_drift": 0,
            "hold_state_drift": 0,
            "sandbox_drift": 0,
            "callback_drift": 0,
        }
        mock_sentry.capture_message.assert_not_called()
        mock_record.assert_not_called()
