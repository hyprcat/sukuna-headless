from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.agents.factories import AgentFactory
from apps.billing.factories import CreditWalletFactory
from apps.core.exceptions import Conflict
from apps.schedules.factories import ScheduleExecutionFactory, ScheduleFactory
from apps.schedules.models import Schedule, ScheduleStatus
from apps.schedules.models.execution import ExecutionOutcome, ScheduleExecution
from apps.schedules.tasks.tick import _try_execute
from apps.tools.factories import ToolFactory


@pytest.mark.django_db
class TestScheduleLifecycle:
    def test_pause_active_schedule(self) -> None:
        schedule = ScheduleFactory()
        schedule.pause()
        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.PAUSED
        assert schedule.paused_at is not None
        assert schedule.next_run_at is None

    def test_pause_already_paused_is_noop(self) -> None:
        schedule = ScheduleFactory(paused=True)
        schedule.pause()
        assert schedule.status == ScheduleStatus.PAUSED

    def test_resume_paused_schedule(self) -> None:
        schedule = ScheduleFactory(paused=True)
        schedule.resume()
        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.ACTIVE
        assert schedule.paused_at is None
        assert schedule.next_run_at is not None

    def test_disable_schedule(self) -> None:
        schedule = ScheduleFactory()
        schedule.disable()
        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.DISABLED
        assert schedule.next_run_at is None

    def test_cannot_resume_disabled(self) -> None:
        schedule = ScheduleFactory(disabled=True)
        with pytest.raises(Exception, match="Cannot resume a disabled schedule"):
            schedule.resume()

    def test_cannot_pause_disabled(self) -> None:
        schedule = ScheduleFactory(disabled=True)
        with pytest.raises(Exception, match="Cannot pause a disabled schedule"):
            schedule.pause()

    def test_stale_active_instance_cannot_overwrite_disabled_on_pause(self) -> None:
        schedule = ScheduleFactory()
        Schedule.objects.filter(pk=schedule.pk).update(
            status=ScheduleStatus.DISABLED,
            disabled_at=timezone.now(),
            next_run_at=None,
        )

        with pytest.raises(Conflict, match="Cannot pause a disabled schedule"):
            schedule.pause()

        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.DISABLED
        assert schedule.next_run_at is None

    def test_stale_paused_instance_cannot_overwrite_disabled_on_resume(self) -> None:
        schedule = ScheduleFactory(paused=True)
        Schedule.objects.filter(pk=schedule.pk).update(
            status=ScheduleStatus.DISABLED,
            disabled_at=timezone.now(),
            next_run_at=None,
        )

        with pytest.raises(Conflict, match="Cannot resume a disabled schedule"):
            schedule.resume()

        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.DISABLED
        assert schedule.next_run_at is None


@pytest.mark.django_db
class TestScheduleRecordOutcome:
    def test_record_success_resets_failures_and_advances(self) -> None:
        schedule = ScheduleFactory(consecutive_failures=2)
        old_next = schedule.next_run_at
        schedule.record_success()
        schedule.refresh_from_db()
        assert schedule.consecutive_failures == 0
        assert schedule.last_run_at is not None
        assert schedule.next_run_at != old_next

    def test_record_failure_increments_counter(self) -> None:
        schedule = ScheduleFactory(consecutive_failures=0)
        schedule.record_failure()
        schedule.refresh_from_db()
        assert schedule.consecutive_failures == 1

    def test_consecutive_failures_disables_schedule(self) -> None:
        schedule = ScheduleFactory(consecutive_failures=4)
        schedule.record_failure()
        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.DISABLED


@pytest.mark.django_db
class TestScheduleValidation:
    def test_save_precomputes_next_run_for_active_schedule(self) -> None:
        schedule = ScheduleFactory(next_run_at=None)
        assert schedule.next_run_at is not None

    def test_invalid_cron_rejected(self) -> None:
        schedule = ScheduleFactory.build(cron_expression="invalid cron")
        with pytest.raises(ValidationError) as exc_info:
            schedule.clean()
        assert "cron_expression" in exc_info.value.message_dict

    def test_invalid_cron_rejected_on_save(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ScheduleFactory(cron_expression="invalid cron")
        assert "cron_expression" in exc_info.value.message_dict

    def test_valid_cron_passes(self) -> None:
        schedule = ScheduleFactory.build(cron_expression="*/5 * * * *")
        schedule.clean()

    def test_output_routing_validates_entries(self) -> None:
        schedule = ScheduleFactory.build(output_routing=[{"kind": "bad", "destination": "x"}])
        with pytest.raises(ValidationError) as exc_info:
            schedule.clean()
        assert "output_routing" in exc_info.value.message_dict

    def test_cross_workspace_agent_rejected_on_save(self) -> None:
        schedule = ScheduleFactory()
        schedule.agent = AgentFactory()
        with pytest.raises(ValidationError) as exc_info:
            schedule.save()
        assert "agent" in exc_info.value.message_dict


@pytest.mark.django_db
class TestScheduleQuerySet:
    def test_due_returns_active_past_next_run(self) -> None:
        due = ScheduleFactory(due_now=True)
        ScheduleFactory()  # not due
        ScheduleFactory(paused=True)
        result = list(Schedule.objects.due())
        assert due in result
        assert len(result) == 1

    def test_due_orders_by_oldest_next_run(self) -> None:
        now = timezone.now()
        later = ScheduleFactory(next_run_at=now - timedelta(minutes=5))
        earlier = ScheduleFactory(next_run_at=now - timedelta(hours=1))
        assert list(Schedule.objects.due(now=now)) == [earlier, later]

    def test_for_workspace_filters(self) -> None:
        s1 = ScheduleFactory()
        ScheduleFactory()  # different workspace
        qs = Schedule.objects.for_workspace(s1.workspace_id)
        assert list(qs) == [s1]


@pytest.mark.django_db
class TestScheduleExecution:
    def test_execution_is_append_only_for_instance_updates(self) -> None:
        execution = ScheduleExecutionFactory()
        execution.outcome = ExecutionOutcome.SKIPPED
        with pytest.raises(Conflict, match="append-only"):
            execution.save()

    def test_execution_is_append_only_for_instance_deletes(self) -> None:
        execution = ScheduleExecutionFactory()
        with pytest.raises(Conflict, match="append-only"):
            execution.delete()

    def test_execution_is_append_only_for_queryset_updates(self) -> None:
        execution = ScheduleExecutionFactory()
        with pytest.raises(Conflict, match="append-only"):
            ScheduleExecution.objects.filter(pk=execution.pk).update(
                outcome=ExecutionOutcome.SKIPPED
            )

    def test_execution_is_append_only_for_queryset_deletes(self) -> None:
        execution = ScheduleExecutionFactory()
        with pytest.raises(Conflict, match="append-only"):
            ScheduleExecution.objects.filter(pk=execution.pk).delete()


@pytest.mark.django_db
class TestScheduleTick:
    def test_stale_paused_schedule_id_is_not_executed(self) -> None:
        now = timezone.now()
        schedule = ScheduleFactory(due_now=True)
        Schedule.objects.filter(pk=schedule.pk).update(
            status=ScheduleStatus.PAUSED,
            next_run_at=now - timedelta(minutes=1),
        )

        assert _try_execute(schedule.pk, now) is False
        assert ScheduleExecution.objects.filter(schedule=schedule).count() == 0

    def test_tick_checks_agent_assigned_tool_access(self) -> None:
        schedule = ScheduleFactory(due_now=True)
        self._fund_workspace(schedule)
        denied_tool = ToolFactory(workspace=schedule.workspace)
        allowed_tool = ToolFactory(workspace=schedule.workspace)
        schedule.agent.assign_tool(denied_tool)
        schedule.target_end_user.profile.allowed_tools.add(allowed_tool)

        assert _try_execute(schedule.pk, timezone.now()) is True

        execution = ScheduleExecution.objects.get(schedule=schedule)
        assert execution.outcome == ExecutionOutcome.SKIPPED
        assert "TOOL_NOT_ALLOWED" in execution.skip_reason

    def _fund_workspace(self, schedule: Schedule) -> None:
        wallet = CreditWalletFactory(workspace=schedule.workspace)
        wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="schedule-test")
