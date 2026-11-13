from __future__ import annotations

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from django.db import transaction

from apps.core.events import record_event
from apps.runs.models.records import RunEvent
from apps.runs.models.run import Run, RunStatus
from apps.runs.models.sandbox_instance import SandboxInstance, SandboxState
from config.runtime import runtime
from integrations import e2b

_log = structlog.get_logger(__name__)

_ACTIVE_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)


def _has_pending_hitl(instance: SandboxInstance) -> bool:
    if not instance.conversation_id:
        return False
    run_qs = Run.objects.filter(
        conversation__conversation_uid=instance.conversation_id,
        status__in=_ACTIVE_STATUSES,
    )
    if not run_qs.exists():
        return False
    run = run_qs.first()
    assert run is not None
    events = RunEvent.objects.filter(run=run)
    requested = events.filter(event_type="hitl_requested").count()
    responded = events.filter(event_type="hitl_responded").count()
    return requested > responded


@shared_task
def sweep_idle_sandboxes() -> int:
    idle_ids = list(
        SandboxInstance.objects.idle_past(runtime.sandbox_max_idle_seconds).values_list(
            "pk", flat=True
        )[:500]
    )
    count = 0
    for pk in idle_ids:
        if _try_terminate(pk):
            count += 1
    _log.info("sweep_idle_sandboxes_completed", terminated=count, checked=len(idle_ids))
    return count


@transaction.atomic
def _try_terminate(pk: int) -> bool:
    try:
        instance = SandboxInstance.objects.select_for_update(skip_locked=True, of=("self",)).get(
            pk=pk
        )
    except SandboxInstance.DoesNotExist:
        return False
    if instance.sandbox_state != SandboxState.PAUSED or instance.current_run_id is not None:
        return False
    if _has_pending_hitl(instance):
        return False
    async_to_sync(e2b.terminate_sandbox)(instance.sandbox_id)
    instance.mark_terminated()
    record_event(
        "sandbox_idle_terminated",
        distinct_id=str(instance.workspace_id),
        properties={"sandbox_id": instance.sandbox_id},
    )
    return True
