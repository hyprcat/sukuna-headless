from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.schedules.models import Schedule, ScheduleStatus
from apps.schedules.models.execution import ExecutionOutcome, ScheduleExecution
from apps.schedules.tasks.dispatch import check_schedule_controls, dispatch_schedule

if TYPE_CHECKING:
    from datetime import datetime

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Claim:
    """Outcome of locking a due schedule: dispatch when ``model_tier`` is set."""

    schedule: Schedule
    model_tier: str


@shared_task
def tick_due_schedules() -> int:
    now = timezone.now()
    due_ids = list(Schedule.objects.due(now=now).values_list("pk", flat=True)[:500])
    count = 0
    for schedule_id in due_ids:
        if _try_execute(schedule_id, now):
            count += 1
    _log.info("schedules_tick_completed", executed=count)
    return count


def _try_execute(schedule_id: int, fire_time: datetime) -> bool:
    claim = _claim(schedule_id, fire_time)
    if claim is None:
        return False
    if claim.model_tier:
        # Dispatch outside the lock — never hold the schedule row across a
        # sandbox spawn / manifest POST.
        dispatch_schedule(claim.schedule, fire_time, claim.model_tier)
    return True


@transaction.atomic
def _claim(schedule_id: int, fire_time: datetime) -> _Claim | None:
    try:
        schedule = (
            Schedule.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("agent", "target_end_user", "workspace__wallet")
            .select_related("target_end_user__workspace__wallet", "target_end_user__profile")
            .prefetch_related("agent__tools", "agent__knowledge_bases")
            .get(pk=schedule_id)
        )
    except Schedule.DoesNotExist:
        return None
    if schedule.status != ScheduleStatus.ACTIVE:
        return None
    if schedule.next_run_at is None or schedule.next_run_at > fire_time:
        return None
    return _evaluate(schedule, fire_time)


def _evaluate(schedule: Schedule, fire_time: datetime) -> _Claim:
    model_tier, denial = check_schedule_controls(schedule)
    if denial:
        _skip(schedule, fire_time, denial)
        return _Claim(schedule=schedule, model_tier="")
    # Advance the next fire time inside the lock so an overlapping tick skips
    # this row; the final cadence is set by record_success / record_failure.
    schedule.advance_next_run()
    return _Claim(schedule=schedule, model_tier=model_tier or "")


def _skip(schedule: Schedule, fire_time: datetime, reason: str) -> None:
    ScheduleExecution.objects.create(
        schedule=schedule,
        outcome=ExecutionOutcome.SKIPPED,
        scheduled_for=fire_time,
        skip_reason=reason,
    )
    schedule.advance_next_run()
    _log.info("schedule_skipped", schedule_id=schedule.pk, reason=reason)
