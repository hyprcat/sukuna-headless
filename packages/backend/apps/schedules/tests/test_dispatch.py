"""Tests for the schedule dispatcher (Phase 8I).

The dispatcher provisions a real run for a due schedule — sandbox acquisition,
run + hold + manifest records, signed manifest POST — and applies the
schedule's failure-handling policy. E2B is mocked via ``patched_e2b_env``.
"""

from __future__ import annotations

import json
import os

import pytest

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.core.exceptions import SandboxError
from apps.runs.models import Run, RunManifestRecord
from apps.runs.tests.conftest import patched_e2b_env, setup_run_env
from apps.schedules.factories import ScheduleFactory
from apps.schedules.models import FailureHandling
from apps.schedules.models.execution import ExecutionOutcome, ScheduleExecution
from apps.schedules.tasks.dispatch import run_now
from apps.schedules.tasks.tick import tick_due_schedules

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

pytestmark = pytest.mark.django_db(transaction=True)


def _due_schedule(**kwargs: object) -> object:
    ws, agent, eu, _wallet = setup_run_env()
    return ScheduleFactory(
        workspace=ws,
        agent=agent,
        target_end_user=eu,
        due_now=True,
        **kwargs,
    )


class TestDispatchHappyPath:
    def test_creates_run_hold_manifest_and_links_execution(self) -> None:
        schedule = _due_schedule()
        with patched_e2b_env() as mocks:
            executed = tick_due_schedules()

        assert executed == 1
        run = Run.objects.get()
        assert run.is_scheduled is True
        assert run.agent_id == schedule.agent_id
        assert run.end_user_id == schedule.target_end_user_id

        hold = BillingHold.objects.get(run=run)
        assert hold.status == HoldStatus.ACTIVE
        assert hold.amount_reserved_usd > 0
        assert RunManifestRecord.objects.filter(run=run).exists()

        execution = ScheduleExecution.objects.get(schedule=schedule)
        assert execution.outcome == ExecutionOutcome.SUCCESS
        assert execution.run_id == run.pk
        mocks["post_manifest"].assert_awaited_once()

    def test_scheduled_manifest_uses_auto_deny_hitl(self) -> None:
        _due_schedule()
        with patched_e2b_env() as mocks:
            tick_due_schedules()

        posted_body = mocks["post_manifest"].await_args.args[1]
        manifest = json.loads(posted_body)
        assert manifest["hitl_mode"] == "auto_deny"

    def test_success_resets_failures_and_advances(self) -> None:
        schedule = _due_schedule()
        with patched_e2b_env():
            tick_due_schedules()

        schedule.refresh_from_db()
        assert schedule.consecutive_failures == 0
        assert schedule.last_run_at is not None


class TestDispatchControlDenial:
    def test_no_credits_skips_without_spawning(self) -> None:
        ws, agent, eu, _wallet = setup_run_env(credits=0)
        schedule = ScheduleFactory(workspace=ws, agent=agent, target_end_user=eu, due_now=True)

        with patched_e2b_env() as mocks:
            executed = tick_due_schedules()

        assert executed == 1
        assert not Run.objects.exists()
        mocks["spawn"].assert_not_awaited()
        execution = ScheduleExecution.objects.get(schedule=schedule)
        assert execution.outcome == ExecutionOutcome.SKIPPED


class TestDispatchFailureHandling:
    def test_e2b_error_with_retry_records_failure_and_releases_hold(self) -> None:
        schedule = _due_schedule(failure_handling=FailureHandling.RETRY)
        with patched_e2b_env() as mocks:
            mocks["post_manifest"].side_effect = SandboxError("manifest rejected")
            executed = tick_due_schedules()

        assert executed == 1
        execution = ScheduleExecution.objects.get(schedule=schedule)
        assert execution.outcome == ExecutionOutcome.FAILED
        assert "manifest rejected" in execution.error_message

        schedule.refresh_from_db()
        assert schedule.consecutive_failures == 1

        hold = BillingHold.objects.get()
        assert hold.status == HoldStatus.RELEASED

    def test_e2b_error_with_skip_records_skipped_without_penalty(self) -> None:
        schedule = _due_schedule(failure_handling=FailureHandling.SKIP)
        with patched_e2b_env() as mocks:
            mocks["post_manifest"].side_effect = SandboxError("boom")
            tick_due_schedules()

        execution = ScheduleExecution.objects.get(schedule=schedule)
        assert execution.outcome == ExecutionOutcome.SKIPPED
        schedule.refresh_from_db()
        assert schedule.consecutive_failures == 0


class TestRunNow:
    def test_run_now_dispatches_without_touching_cadence(self) -> None:
        ws, agent, eu, _wallet = setup_run_env()
        schedule = ScheduleFactory(workspace=ws, agent=agent, target_end_user=eu)
        next_run_before = schedule.next_run_at

        with patched_e2b_env():
            execution = run_now(schedule)

        assert execution.outcome == ExecutionOutcome.SUCCESS
        run = Run.objects.get()
        assert run.is_scheduled is True
        assert execution.run_id == run.pk

        schedule.refresh_from_db()
        assert schedule.next_run_at == next_run_before
        assert schedule.last_run_at is None

    def test_run_now_denied_records_skip(self) -> None:
        ws, agent, eu, _wallet = setup_run_env(credits=0)
        schedule = ScheduleFactory(workspace=ws, agent=agent, target_end_user=eu)

        with patched_e2b_env() as mocks:
            execution = run_now(schedule)

        assert execution.outcome == ExecutionOutcome.SKIPPED
        assert not Run.objects.exists()
        mocks["spawn"].assert_not_awaited()
