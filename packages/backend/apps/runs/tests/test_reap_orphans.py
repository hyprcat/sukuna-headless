from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.billing.factories import BillingHoldFactory
from apps.billing.models.hold import BillingHold, HoldStatus
from apps.runs.factories import RunFactory
from apps.runs.models.run import Run, RunStatus
from apps.runs.tasks.reap_orphans import reap_orphan_runs

pytestmark = pytest.mark.django_db(transaction=True)

LEASE_60S = {"max_runtime_seconds": 60, "max_total_tokens": 100_000, "max_cost_usd": "10.00"}
GRACE = 60


def _make_orphan(
    *,
    status: str = RunStatus.RUNNING,
    age_seconds: int = 200,
    cost: Decimal = Decimal("0"),
) -> tuple[Run, BillingHold]:
    run = RunFactory(
        status=status,
        started_at=timezone.now() - timedelta(seconds=age_seconds),
        lease_json=LEASE_60S,
        total_cost_usd=cost,
    )
    hold = BillingHoldFactory(run=run, wallet__workspace=run.workspace)
    return run, hold


class TestReapOrphanRuns:
    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_orphaned_running_run_reaped(self, mock_runtime):
        mock_runtime.sandbox_grace_period_seconds = GRACE
        run, _hold = _make_orphan(age_seconds=200)

        count = reap_orphan_runs()

        assert count == 1
        run.refresh_from_db()
        assert run.status == RunStatus.FAILED
        assert run.finished_at is not None
        assert "Orphaned" in run.error_message

    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_orphaned_queued_run_reaped(self, mock_runtime):
        mock_runtime.sandbox_grace_period_seconds = GRACE
        run, _hold = _make_orphan(status=RunStatus.QUEUED, age_seconds=200)

        count = reap_orphan_runs()

        assert count == 1
        run.refresh_from_db()
        assert run.status == RunStatus.FAILED

    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_non_orphaned_run_untouched(self, mock_runtime):
        mock_runtime.sandbox_grace_period_seconds = GRACE
        run, _hold = _make_orphan(age_seconds=30)

        count = reap_orphan_runs()

        assert count == 0
        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING

    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_hold_released_when_no_cost(self, mock_runtime):
        mock_runtime.sandbox_grace_period_seconds = GRACE
        _run, hold = _make_orphan(age_seconds=200, cost=Decimal("0"))

        reap_orphan_runs()

        hold.refresh_from_db()
        assert hold.status == HoldStatus.RELEASED

    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_hold_settled_when_partial_cost(self, mock_runtime):
        mock_runtime.sandbox_grace_period_seconds = GRACE
        _run, hold = _make_orphan(
            age_seconds=200,
            cost=Decimal("3.50"),
        )

        reap_orphan_runs()

        hold.refresh_from_db()
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("3.50")

    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_terminal_run_skipped(self, mock_runtime):
        mock_runtime.sandbox_grace_period_seconds = GRACE
        run = RunFactory(finished=True, lease_json=LEASE_60S)
        BillingHoldFactory(
            run=run,
            wallet__workspace=run.workspace,
            status=HoldStatus.SETTLED,
            amount_consumed_usd=Decimal("5.00"),
            settled_at=timezone.now(),
        )

        count = reap_orphan_runs()

        assert count == 0

    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_run_without_lease_not_reaped(self, mock_runtime):
        mock_runtime.sandbox_grace_period_seconds = GRACE
        run = RunFactory(
            running=True,
            lease_json={},
        )
        BillingHoldFactory(run=run, wallet__workspace=run.workspace)

        count = reap_orphan_runs()

        assert count == 0
        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING

    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_uses_last_callback_at_as_anchor(self, mock_runtime):
        mock_runtime.sandbox_grace_period_seconds = GRACE
        now = timezone.now()
        run = RunFactory(
            running=True,
            started_at=now - timedelta(seconds=200),
            last_callback_at=now - timedelta(seconds=30),
            lease_json=LEASE_60S,
        )
        BillingHoldFactory(run=run, wallet__workspace=run.workspace)

        count = reap_orphan_runs()

        assert count == 0
        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING

    @patch("apps.runs.tasks.reap_orphans.runtime")
    def test_run_without_hold_excluded(self, mock_runtime):
        """Runs without billing holds are excluded from reaping entirely."""
        mock_runtime.sandbox_grace_period_seconds = GRACE
        RunFactory(
            running=True,
            started_at=timezone.now() - timedelta(seconds=200),
            lease_json=LEASE_60S,
        )

        count = reap_orphan_runs()

        assert count == 0
