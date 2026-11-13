from __future__ import annotations

from datetime import timedelta

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from django.utils import timezone

from apps.agents.models import Agent
from apps.core.events import record_event
from apps.runs.models.run import Run
from apps.runs.models.sandbox_instance import SandboxInstance, SandboxState
from apps.runs.services import sandbox_pool
from config.runtime import runtime
from integrations import e2b

_log = structlog.get_logger(__name__)

_WARM_STATES = (SandboxState.PAUSED, SandboxState.BOOTING)


def _recent_agents() -> list[Agent]:
    cutoff = timezone.now() - timedelta(hours=1)
    agent_ids = (
        Run.objects.filter(created_at__gte=cutoff).values_list("agent_id", flat=True).distinct()
    )
    return list(Agent.objects.filter(pk__in=agent_ids))


def _warm_count_for(agent: Agent) -> int:
    return SandboxInstance.objects.filter(
        agent=agent,
        sandbox_state__in=_WARM_STATES,
        current_run__isnull=True,
    ).count()


def _global_warm_count() -> int:
    return SandboxInstance.objects.filter(
        sandbox_state__in=_WARM_STATES,
        current_run__isnull=True,
    ).count()


def _spawn_for_agent(agent: Agent, global_warm: int) -> tuple[int, int]:
    target = sandbox_pool.compute_target_pool_size(agent)
    existing = _warm_count_for(agent)
    to_spawn = max(
        0,
        min(
            target - existing,
            runtime.sandbox_pool_max_per_agent - existing,
            runtime.sandbox_pool_max_warm - global_warm,
        ),
    )
    spawned = 0
    for _ in range(to_spawn):
        handle = async_to_sync(e2b.spawn_sandbox)(ttl_seconds=runtime.sandbox_boot_timeout_seconds)
        SandboxInstance.objects.create(
            sandbox_id=handle.sandbox_id,
            sandbox_url=handle.sandbox_url,
            workspace=agent.workspace,
            agent=agent,
            sandbox_state=SandboxState.BOOTING,
            boot_started_at=timezone.now(),
        )
        global_warm += 1
        spawned += 1
    return spawned, global_warm


@shared_task
def pre_warm_pools() -> int:
    agents = _recent_agents()
    global_warm = _global_warm_count()
    total = 0
    for agent in agents:
        spawned, global_warm = _spawn_for_agent(agent, global_warm)
        total += spawned
        if spawned:
            record_event(
                "sandbox_pre_warmed",
                distinct_id=str(agent.workspace_id),
                properties={"agent_id": str(agent.pk), "spawned": spawned},
            )
    _log.info("pre_warm_pools_completed", agents=len(agents), spawned=total)
    return total
