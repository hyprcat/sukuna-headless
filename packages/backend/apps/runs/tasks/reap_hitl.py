from __future__ import annotations

import structlog
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.core.events import record_event
from apps.runs.models.records import RunEvent
from apps.runs.models.run import Run
from config.runtime import runtime

_log = structlog.get_logger(__name__)


@shared_task
def reap_orphan_hitl() -> int:
    now = timezone.now()
    cutoff = now - timezone.timedelta(seconds=runtime.hitl_timeout_seconds)
    stale_run_ids = list(
        RunEvent.objects.filter(event_type="hitl_requested", created_at__lte=cutoff)
        .values_list("run_id", flat=True)
        .distinct()[:500]
    )
    count = sum(_try_deny(run_id) for run_id in stale_run_ids)
    _log.info("reap_orphan_hitl_completed", denied=count, checked=len(stale_run_ids))
    return count


@transaction.atomic
def _try_deny(run_id: int) -> bool:
    try:
        run = Run.objects.select_for_update(skip_locked=True, of=("self",)).get(pk=run_id)
    except Run.DoesNotExist:
        return False
    if run.is_terminal:
        return False
    if not _is_stale_hitl(run):
        return False
    run.cancel()
    _handle_hold(run)
    record_event(
        "hitl_auto_denied",
        distinct_id=str(run.workspace_id),
        properties={"run_id": str(run.run_uid)},
    )
    return True


def _is_stale_hitl(run: Run) -> bool:
    requested = RunEvent.objects.filter(run=run, event_type="hitl_requested").count()
    responded = RunEvent.objects.filter(run=run, event_type="hitl_responded").count()
    return requested > responded


def _handle_hold(run: Run) -> None:
    try:
        hold = BillingHold.objects.get(run=run)
    except BillingHold.DoesNotExist:
        return
    if hold.status != HoldStatus.ACTIVE:
        return
    if run.total_cost_usd > 0:
        hold.settle(min(run.total_cost_usd, hold.amount_reserved_usd))
    else:
        hold.release()
