from __future__ import annotations

import structlog
from celery import shared_task
from django.db.models import Count, Max
from django.utils import timezone

from apps.core.events import record_event
from apps.runs.models.records import RunEvent
from apps.runs.models.run import Run

_log = structlog.get_logger(__name__)

_GAP_PERSIST_MINUTES = 10


@shared_task
def detect_callback_gaps() -> int:
    now = timezone.now()
    active_ids = list(Run.objects.active().values_list("pk", flat=True)[:500])
    count = sum(_check_run(run_id, now) for run_id in active_ids)
    _log.info("detect_callback_gaps_completed", gaps=count, checked=len(active_ids))
    return count


def _check_run(run_id: int, now: timezone.datetime) -> bool:
    agg = RunEvent.objects.filter(run_id=run_id).aggregate(
        mx=Max("sequence_no"), cnt=Count("sequence_no")
    )
    mx, cnt = agg["mx"], agg["cnt"]
    if cnt is None or cnt == 0 or cnt >= mx:
        return False
    _log.warning("callback_gap", run_id=run_id, max_sequence=mx, present_count=cnt)
    if _is_persistent(run_id, now):
        _emit_gap_event(run_id, mx, cnt)
    return True


def _is_persistent(run_id: int, now: timezone.datetime) -> bool:
    run = Run.objects.filter(pk=run_id).only("last_callback_at").first()
    if run is None or run.last_callback_at is None:
        return False
    return (now - run.last_callback_at) > timezone.timedelta(minutes=_GAP_PERSIST_MINUTES)


def _emit_gap_event(run_id: int, mx: int, cnt: int) -> None:
    run = Run.objects.filter(pk=run_id).only("workspace_id", "run_uid").first()
    if run is None:
        return
    record_event(
        "callback_gap_detected",
        distinct_id=str(run.workspace_id),
        properties={"run_id": str(run.run_uid), "max_sequence": mx, "present_count": cnt},
    )
