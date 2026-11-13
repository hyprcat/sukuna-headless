from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.billing.factories import BillingHoldFactory
from apps.billing.models.hold import HoldStatus
from apps.runs.factories import RunEventFactory, RunFactory
from apps.runs.models.run import RunStatus
from apps.runs.tasks.reap_hitl import reap_orphan_hitl

pytestmark = pytest.mark.django_db(transaction=True)

TIMEOUT = 300


def _make_stale_hitl_run(*, cost: Decimal = Decimal("0")):
    now = timezone.now()
    run = RunFactory(running=True, total_cost_usd=cost)
    with freeze_time(now - timedelta(seconds=400)):
        RunEventFactory(run=run, sequence_no=1, event_type="hitl_requested", payload={})
    hold = BillingHoldFactory(run=run, wallet__workspace=run.workspace)
    return run, hold


class TestReapOrphanHitl:
    @patch("apps.runs.tasks.reap_hitl.runtime")
    def test_stale_hitl_run_cancelled(self, mock_runtime):
        mock_runtime.hitl_timeout_seconds = TIMEOUT
        run, _hold = _make_stale_hitl_run()

        count = reap_orphan_hitl()

        assert count == 1
        run.refresh_from_db()
        assert run.status == RunStatus.CANCELLED

    @patch("apps.runs.tasks.reap_hitl.runtime")
    def test_stale_hitl_hold_released_when_no_cost(self, mock_runtime):
        mock_runtime.hitl_timeout_seconds = TIMEOUT
        _run, hold = _make_stale_hitl_run(cost=Decimal("0"))

        reap_orphan_hitl()

        hold.refresh_from_db()
        assert hold.status == HoldStatus.RELEASED

    @patch("apps.runs.tasks.reap_hitl.runtime")
    def test_stale_hitl_hold_settled_when_has_cost(self, mock_runtime):
        mock_runtime.hitl_timeout_seconds = TIMEOUT
        _run, hold = _make_stale_hitl_run(cost=Decimal("2.00"))

        reap_orphan_hitl()

        hold.refresh_from_db()
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("2.00")

    @patch("apps.runs.tasks.reap_hitl.runtime")
    def test_recent_hitl_untouched(self, mock_runtime):
        mock_runtime.hitl_timeout_seconds = TIMEOUT
        run = RunFactory(running=True)
        RunEventFactory(run=run, sequence_no=1, event_type="hitl_requested", payload={})
        BillingHoldFactory(run=run, wallet__workspace=run.workspace)

        count = reap_orphan_hitl()

        assert count == 0
        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING

    @patch("apps.runs.tasks.reap_hitl.runtime")
    def test_responded_hitl_not_reaped(self, mock_runtime):
        mock_runtime.hitl_timeout_seconds = TIMEOUT
        now = timezone.now()
        run = RunFactory(running=True)
        with freeze_time(now - timedelta(seconds=400)):
            RunEventFactory(run=run, sequence_no=1, event_type="hitl_requested", payload={})
        RunEventFactory(run=run, sequence_no=2, event_type="hitl_responded", payload={})
        BillingHoldFactory(run=run, wallet__workspace=run.workspace)

        count = reap_orphan_hitl()

        assert count == 0
        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING
