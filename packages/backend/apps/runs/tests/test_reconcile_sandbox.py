from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from apps.billing.factories import BillingHoldFactory
from apps.billing.models.hold import HoldStatus
from apps.runs.factories import RunFactory, SandboxInstanceFactory
from apps.runs.models.run import RunStatus
from apps.runs.models.sandbox_instance import SandboxState
from apps.runs.tasks.reconcile_sandbox import reconcile_sandbox_state

pytestmark = pytest.mark.django_db(transaction=True)


class TestReconcileSandboxState:
    @patch("apps.runs.tasks.reconcile_sandbox.e2b.terminate_sandbox", new_callable=AsyncMock)
    @patch("apps.runs.tasks.reconcile_sandbox.e2b.list_sandbox_states", new_callable=AsyncMock)
    def test_dropped_sandbox_terminated(self, mock_list, mock_terminate):
        mock_list.return_value = {}
        instance = SandboxInstanceFactory(running=True, sandbox_id="sbx-gone")

        result = reconcile_sandbox_state()

        instance.refresh_from_db()
        assert instance.sandbox_state == SandboxState.TERMINATED
        assert result["terminated"] == 1
        mock_terminate.assert_not_called()

    @patch("apps.runs.tasks.reconcile_sandbox.e2b.terminate_sandbox", new_callable=AsyncMock)
    @patch("apps.runs.tasks.reconcile_sandbox.e2b.list_sandbox_states", new_callable=AsyncMock)
    def test_dropped_sandbox_with_run_fails_run(self, mock_list, mock_terminate):
        mock_list.return_value = {}
        run = RunFactory(running=True, total_cost_usd=Decimal("2.00"))
        SandboxInstanceFactory(running=True, sandbox_id="sbx-gone", current_run=run)
        BillingHoldFactory(run=run, wallet__workspace=run.workspace)

        reconcile_sandbox_state()

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED
        assert "reconciled" in run.error_message

    @patch("apps.runs.tasks.reconcile_sandbox.e2b.terminate_sandbox", new_callable=AsyncMock)
    @patch("apps.runs.tasks.reconcile_sandbox.e2b.list_sandbox_states", new_callable=AsyncMock)
    def test_dropped_sandbox_with_run_settles_hold(self, mock_list, mock_terminate):
        mock_list.return_value = {}
        run = RunFactory(running=True, total_cost_usd=Decimal("3.50"))
        instance = SandboxInstanceFactory(running=True, sandbox_id="sbx-gone", current_run=run)
        hold = BillingHoldFactory(run=run, wallet__workspace=run.workspace)

        reconcile_sandbox_state()

        hold.refresh_from_db()
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("3.50")
        instance.refresh_from_db()
        assert instance.sandbox_state == SandboxState.TERMINATED

    @patch("apps.runs.tasks.reconcile_sandbox.e2b.terminate_sandbox", new_callable=AsyncMock)
    @patch("apps.runs.tasks.reconcile_sandbox.e2b.list_sandbox_states", new_callable=AsyncMock)
    def test_alive_sandbox_untouched(self, mock_list, mock_terminate):
        mock_list.return_value = {"sbx-alive": "running"}
        instance = SandboxInstanceFactory(running=True, sandbox_id="sbx-alive")

        result = reconcile_sandbox_state()

        instance.refresh_from_db()
        assert instance.sandbox_state == SandboxState.RUNNING
        assert result["terminated"] == 0

    @patch("apps.runs.tasks.reconcile_sandbox.e2b.terminate_sandbox", new_callable=AsyncMock)
    @patch("apps.runs.tasks.reconcile_sandbox.e2b.list_sandbox_states", new_callable=AsyncMock)
    def test_ghost_sandbox_killed(self, mock_list, mock_terminate):
        mock_list.return_value = {"sbx-ghost": "running"}
        SandboxInstanceFactory(terminated=True, sandbox_id="sbx-ghost")

        result = reconcile_sandbox_state()

        mock_terminate.assert_called_once_with("sbx-ghost")
        assert result["killed"] == 1

    @patch("apps.runs.tasks.reconcile_sandbox.e2b.terminate_sandbox", new_callable=AsyncMock)
    @patch("apps.runs.tasks.reconcile_sandbox.e2b.list_sandbox_states", new_callable=AsyncMock)
    def test_terminated_not_in_actual_untouched(self, mock_list, mock_terminate):
        mock_list.return_value = {}
        SandboxInstanceFactory(terminated=True, sandbox_id="sbx-dead")

        result = reconcile_sandbox_state()

        mock_terminate.assert_not_called()
        assert result["terminated"] == 0
        assert result["killed"] == 0
