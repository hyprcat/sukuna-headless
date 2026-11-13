from __future__ import annotations

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.core.events import record_event
from apps.runs.models.run import Run, RunStatus
from apps.runs.models.sandbox_instance import SandboxInstance, SandboxState
from integrations import e2b

_log = structlog.get_logger(__name__)

_BATCH = 500


@shared_task
def reconcile_sandbox_state() -> dict[str, int]:
    actual = async_to_sync(e2b.list_sandbox_states)()
    terminated = _reconcile_dropped(actual)
    killed = _reconcile_ghost(actual)
    _log.info("reconcile_sandbox_state_done", terminated=terminated, killed=killed)
    return {"terminated": terminated, "killed": killed}


def _reconcile_dropped(actual: dict[str, str]) -> int:
    alive_ids = set(actual)
    qs = (
        SandboxInstance.objects.exclude(sandbox_state=SandboxState.TERMINATED)
        .exclude(sandbox_id__in=alive_ids)
        .values_list("pk", flat=True)[:_BATCH]
    )
    count = 0
    for pk in list(qs):
        if _terminate_instance(pk):
            count += 1
    return count


def _reconcile_ghost(actual: dict[str, str]) -> int:
    dead_ids = set(actual)
    qs = (
        SandboxInstance.objects.filter(sandbox_state=SandboxState.TERMINATED)
        .filter(sandbox_id__in=dead_ids)
        .values_list("pk", "sandbox_id", "workspace_id")[:_BATCH]
    )
    count = 0
    for _pk, sbx_id, workspace_id in list(qs):
        async_to_sync(e2b.terminate_sandbox)(sbx_id)
        record_event(
            "sandbox_reconciled_killed",
            distinct_id=str(workspace_id),
            properties={"sandbox_id": sbx_id},
        )
        count += 1
    return count


@transaction.atomic
def _terminate_instance(pk: int) -> bool:
    try:
        instance = SandboxInstance.objects.select_for_update(skip_locked=True).get(pk=pk)
    except SandboxInstance.DoesNotExist:
        return False
    if instance.sandbox_state == SandboxState.TERMINATED:
        return False
    run = _reap_current_run(instance)
    instance.mark_terminated()
    record_event(
        "sandbox_reconciled_terminated",
        distinct_id=str(instance.workspace_id),
        properties={"sandbox_id": instance.sandbox_id},
    )
    run_uid = str(run.run_uid) if run else None
    _log.info("sandbox_terminated_by_reconciler", sandbox_id=instance.sandbox_id, run_uid=run_uid)
    return True


def _reap_current_run(instance: SandboxInstance) -> Run | None:
    if not instance.current_run_id:
        return None
    try:
        run = Run.objects.get(pk=instance.current_run_id)
    except Run.DoesNotExist:
        return None
    if run.is_terminal:
        return None
    now = timezone.now()
    run.status = RunStatus.FAILED
    run.finished_at = now
    run.error_message = "Sandbox terminated out-of-band — reconciled."
    run.save(update_fields=("status", "finished_at", "error_message", "updated_at"))
    _settle_hold(run)
    return run


def _settle_hold(run: Run) -> None:
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
