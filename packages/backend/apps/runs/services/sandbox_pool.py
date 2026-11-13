"""Sandbox pool — acquire, release, and size warm sandboxes."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import SandboxError
from apps.runs.models.sandbox_instance import (
    SandboxInstance,
    SandboxInstanceQuerySet,
    SandboxState,
)
from config.runtime import runtime
from integrations import e2b

if TYPE_CHECKING:
    import uuid

    from apps.agents.models import Agent
    from apps.workspaces.models import Workspace
    from integrations.e2b import SandboxHandle


async def acquire_sandbox(
    agent: Agent,
    workspace: Workspace,
    conversation_id: uuid.UUID | None = None,
) -> SandboxInstance:
    """Acquire a sandbox: conversation affinity -> warm pool -> fresh spawn."""
    instance = await _try_claim_warm(agent, workspace, conversation_id)
    if instance:
        if await _resume_claimed(instance):
            return instance
        return await _spawn_fresh(workspace, agent, conversation_id)
    return await _spawn_fresh(workspace, agent, conversation_id)


async def _resume_claimed(instance: SandboxInstance) -> bool:
    try:
        await e2b.resume_sandbox(
            instance.sandbox_id,
            ttl_seconds=runtime.sandbox_resume_timeout_seconds,
        )
    except SandboxError:
        await sync_to_async(instance.mark_terminated)()
        return False
    else:
        return True


async def _spawn_fresh(
    workspace: Workspace,
    agent: Agent,
    conversation_id: uuid.UUID | None,
) -> SandboxInstance:
    handle = await e2b.spawn_sandbox(
        ttl_seconds=runtime.sandbox_boot_timeout_seconds,
    )
    return await _create_booting(handle, workspace, agent, conversation_id)


async def release_sandbox(instance: SandboxInstance) -> None:
    """Pause a running sandbox for reuse if under pool caps, else terminate.

    Only a RUNNING sandbox can be paused; a still-booting one (e.g. a failed
    provision rolling back) must be terminated.
    """
    pausable = instance.sandbox_state == SandboxState.RUNNING
    if pausable and await _should_keep_warm(instance):
        await e2b.pause_sandbox(instance.sandbox_id)
        await sync_to_async(instance.mark_paused)()
    else:
        await e2b.terminate_sandbox(instance.sandbox_id)
        await sync_to_async(instance.mark_terminated)()


def compute_target_pool_size(agent: Agent) -> int:
    """Trailing 1-hour run frequency heuristic, capped per-agent."""
    from apps.runs.models.run import Run  # noqa: PLC0415

    cutoff = timezone.now() - timedelta(hours=1)
    recent = Run.objects.filter(agent=agent, created_at__gte=cutoff).count()
    if not recent:
        return 0
    return min(math.ceil(recent / 4), runtime.sandbox_pool_max_per_agent)


# -- Private helpers ----------------------------------------------------------


@sync_to_async
def _try_claim_warm(
    agent: Agent,
    workspace: Workspace,
    conversation_id: uuid.UUID | None,
) -> SandboxInstance | None:
    with transaction.atomic():
        if conversation_id:
            inst = _claim_first(
                SandboxInstance.objects.for_workspace(workspace.id)
                .for_conversation(conversation_id)
                .warm()
            )
            if inst:
                return inst
        return _claim_first(
            SandboxInstance.objects.for_workspace(workspace.id).for_agent(agent.id).warm()
        )


def _claim_first(qs: SandboxInstanceQuerySet) -> SandboxInstance | None:
    inst = qs.select_for_update(skip_locked=True).first()
    if inst is None:
        return None
    inst.sandbox_state = SandboxState.RUNNING
    inst.resume_count += 1
    inst.save(update_fields=("sandbox_state", "resume_count", "updated_at"))
    return inst


@sync_to_async
def _create_booting(
    handle: SandboxHandle,
    workspace: Workspace,
    agent: Agent,
    conversation_id: uuid.UUID | None,
) -> SandboxInstance:
    return SandboxInstance.objects.create(
        sandbox_id=handle.sandbox_id,
        workspace=workspace,
        agent=agent,
        conversation_id=conversation_id,
        sandbox_state=SandboxState.BOOTING,
        sandbox_url=handle.sandbox_url,
        boot_started_at=timezone.now(),
    )


@sync_to_async
def _should_keep_warm(instance: SandboxInstance) -> bool:
    if instance.agent_id is not None:
        agent_warm = SandboxInstance.objects.for_agent(instance.agent_id).warm().count()
        if agent_warm >= runtime.sandbox_pool_max_per_agent:
            return False
    global_warm = SandboxInstance.objects.warm().count()
    return global_warm < runtime.sandbox_pool_max_warm
