from __future__ import annotations

import structlog
from celery import shared_task
from django.db import models, transaction
from django.utils import timezone

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.core.events import record_event
from apps.runs.models.run import Run, RunStatus
from config.runtime import runtime

_log = structlog.get_logger(__name__)


@shared_task
def reap_orphan_runs() -> int:
    now = timezone.now()
    orphan_ids = list(
        Run.objects.active()
        .annotate(has_hold=models.Exists(BillingHold.objects.filter(run=models.OuterRef("pk"))))
        .filter(has_hold=True)
        .values_list("pk", flat=True)[:500]
    )
    count = 0
    for run_id in orphan_ids:
        if _try_reap(run_id, now):
            count += 1
    _log.info("reap_orphan_runs_completed", reaped=count, checked=len(orphan_ids))
    return count


@transaction.atomic
def _try_reap(run_id: int, now: timezone.datetime) -> bool:
    try:
        run = Run.objects.select_for_update(skip_locked=True, of=("self",)).get(pk=run_id)
    except Run.DoesNotExist:
        return False
    if run.is_terminal or not _is_orphaned(run, now):
        return False
    _mark_failed(run, now)
    _handle_hold(run)
    _emit_orphan_event(run)
    return True


def _emit_orphan_event(run: Run) -> None:
    _log.info("run_reaped_as_orphan", run_uid=str(run.run_uid))
    record_event(
        "run_orphan_reaped",
        distinct_id=str(run.workspace_id),
        properties={
            "run_id": str(run.run_uid),
            "agent_id": str(run.agent_id),
        },
    )


def _is_orphaned(run: Run, now: timezone.datetime) -> bool:
    lease = run.lease
    if lease is None:
        return False

    anchor = run.last_callback_at or run.started_at or run.created_at
    deadline = anchor + timezone.timedelta(
        seconds=lease.max_runtime_seconds + runtime.sandbox_grace_period_seconds,
    )
    return now >= deadline


def _mark_failed(run: Run, now: timezone.datetime) -> None:
    run.status = RunStatus.FAILED
    run.finished_at = now
    run.error_message = "Orphaned — no sandbox response within lease + grace period."
    run.save(
        update_fields=(
            "status",
            "finished_at",
            "error_message",
            "updated_at",
        ),
    )


def _handle_hold(run: Run) -> None:
    try:
        hold = BillingHold.objects.get(run=run)
    except BillingHold.DoesNotExist:
        return

    if hold.status != HoldStatus.ACTIVE:
        return

    if run.total_cost_usd > 0:
        actual = min(run.total_cost_usd, hold.amount_reserved_usd)
        hold.settle(actual)
    else:
        hold.release()
