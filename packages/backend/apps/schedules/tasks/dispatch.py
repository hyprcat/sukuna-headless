"""Schedule dispatcher — provisions a real run for a due schedule.

Extends the pre-flight tick (``tasks/tick.py``): once a schedule's controls
pass, this acquires a sandbox, creates the run + hold + manifest records, and
posts the signed manifest. Scheduled runs use ``hitl_mode="auto_deny"`` — there
is no live caller to approve a human-in-the-loop request. Failure handling
follows the schedule's configured policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from asgiref.sync import async_to_sync
from django.utils import timezone

from apps.core.events import record_event
from apps.runs.models.run import Run
from apps.runs.services.orchestrator import provision_run
from apps.schedules.models import FailureHandling
from apps.schedules.models.execution import ExecutionOutcome, ScheduleExecution

if TYPE_CHECKING:
    from datetime import datetime

    from apps.schedules.models import Schedule

_log = structlog.get_logger(__name__)


def check_schedule_controls(schedule: Schedule) -> tuple[str | None, str]:
    """Return ``(model_tier, "")`` when the schedule may run, else ``(None, reason)``."""
    from apps.end_users.schemas import Denied  # noqa: PLC0415

    end_user = schedule.target_end_user
    agent = schedule.agent
    if not agent.is_active:
        return None, "Agent is inactive."
    if not end_user.is_active:
        return None, "End user is inactive."
    active = Run.objects.active_count_for_end_user(end_user.pk)
    check = end_user.check_can_run(
        agent,
        list(agent.tools.all()),
        list(agent.knowledge_bases.all()),
        active_run_count=active,
    )
    if isinstance(check, Denied):
        return None, f"End user control denied: {check.reason}"
    return check.model_tier, ""


def dispatch_schedule(
    schedule: Schedule,
    fire_time: datetime,
    model_tier: str,
    *,
    update_schedule: bool = True,
) -> ScheduleExecution:
    """Provision a run for a due schedule, record the outcome, apply failure handling."""
    try:
        run = _provision(schedule, model_tier)
    except Exception as exc:
        # Any provisioning failure (control, billing, or sandbox error) routes
        # through the schedule's configured failure handling.
        return _handle_failure(schedule, fire_time, str(exc), update_schedule=update_schedule)
    return _record_success(schedule, fire_time, run, update_schedule=update_schedule)


def run_now(schedule: Schedule) -> ScheduleExecution:
    """Admin 'Run now' path — control-check then dispatch without touching cadence."""
    model_tier, denial = check_schedule_controls(schedule)
    fire_time = timezone.now()
    if model_tier is None:
        return _record_skip(schedule, fire_time, denial)
    return dispatch_schedule(schedule, fire_time, model_tier, update_schedule=False)


def _provision(schedule: Schedule, model_tier: str) -> Run:
    run, _instance = async_to_sync(provision_run)(
        workspace=schedule.workspace,
        agent=schedule.agent,
        end_user=schedule.target_end_user,
        prompt=schedule.prompt,
        model_tier=model_tier,
        tools=list(schedule.agent.tools.all()),
        knowledge=list(schedule.agent.knowledge_bases.all()),
        hitl_mode="auto_deny",
        is_scheduled=True,
    )
    return run


def _record_success(
    schedule: Schedule,
    fire_time: datetime,
    run: Run,
    *,
    update_schedule: bool,
) -> ScheduleExecution:
    execution = ScheduleExecution.objects.create(
        schedule=schedule,
        run=run,
        outcome=ExecutionOutcome.SUCCESS,
        scheduled_for=fire_time,
        started_at=timezone.now(),
    )
    if update_schedule:
        schedule.record_success()
    _log.info("schedule_dispatched", schedule_id=schedule.pk, run_id=str(run.run_uid))
    return execution


def _record_skip(schedule: Schedule, fire_time: datetime, reason: str) -> ScheduleExecution:
    return ScheduleExecution.objects.create(
        schedule=schedule,
        outcome=ExecutionOutcome.SKIPPED,
        scheduled_for=fire_time,
        skip_reason=reason,
    )


def _handle_failure(
    schedule: Schedule,
    fire_time: datetime,
    error: str,
    *,
    update_schedule: bool,
) -> ScheduleExecution:
    handling = schedule.failure_handling
    is_skip = handling == FailureHandling.SKIP
    execution = ScheduleExecution.objects.create(
        schedule=schedule,
        outcome=ExecutionOutcome.SKIPPED if is_skip else ExecutionOutcome.FAILED,
        scheduled_for=fire_time,
        skip_reason=error if is_skip else "",
        error_message="" if is_skip else error,
    )
    _apply_failure_handling(schedule, handling, error, update_schedule=update_schedule)
    return execution


def _apply_failure_handling(
    schedule: Schedule,
    handling: str,
    error: str,
    *,
    update_schedule: bool,
) -> None:
    if handling == FailureHandling.SKIP:
        _log.info("schedule_dispatch_skipped", schedule_id=schedule.pk, error=error)
        return
    if handling == FailureHandling.ALERT:
        record_event(
            "schedule_dispatch_alert",
            distinct_id=str(schedule.workspace_id),
            properties={"schedule_id": str(schedule.pk), "error": error},
        )
    if handling != FailureHandling.LOG_SILENT:
        _log.warning(
            "schedule_dispatch_failed",
            schedule_id=schedule.pk,
            handling=handling,
            error=error,
        )
    if update_schedule:
        schedule.record_failure()
