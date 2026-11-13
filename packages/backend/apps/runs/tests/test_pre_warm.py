from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.utils import timezone

from apps.agents.factories import AgentFactory
from apps.runs.factories import RunFactory, SandboxInstanceFactory
from apps.runs.models.sandbox_instance import SandboxInstance, SandboxState
from apps.runs.tasks.pre_warm import pre_warm_pools
from integrations.e2b import SandboxHandle

pytestmark = pytest.mark.django_db(transaction=True)


def _make_handle(n: int = 0) -> SandboxHandle:
    return SandboxHandle(sandbox_id=f"sbx-{n}", sandbox_url=f"https://sbx-{n}.example.com")


@patch("apps.runs.tasks.pre_warm.runtime")
@patch("apps.runs.tasks.pre_warm.e2b.spawn_sandbox", new_callable=AsyncMock)
def test_pool_expanded_when_under_target(mock_spawn: AsyncMock, mock_runtime: MagicMock) -> None:
    mock_runtime.sandbox_pool_max_per_agent = 5
    mock_runtime.sandbox_pool_max_warm = 10
    mock_runtime.sandbox_boot_timeout_seconds = 30

    call_count = 0

    async def _spawn(**kwargs: object) -> SandboxHandle:
        nonlocal call_count
        h = _make_handle(call_count)
        call_count += 1
        return h

    mock_spawn.side_effect = _spawn

    agent = AgentFactory()
    # 8 recent runs → compute_target_pool_size returns ceil(8/4)=2, capped at 5 → target=2
    cutoff = timezone.now() - timedelta(minutes=30)
    for _ in range(8):
        RunFactory(agent=agent, workspace=agent.workspace, created_at=cutoff)

    count = pre_warm_pools()

    assert count == 2
    assert mock_spawn.await_count == 2
    booting = SandboxInstance.objects.filter(
        agent=agent, sandbox_state=SandboxState.BOOTING
    ).count()
    assert booting == 2


@patch("apps.runs.tasks.pre_warm.runtime")
@patch("apps.runs.tasks.pre_warm.e2b.spawn_sandbox", new_callable=AsyncMock)
def test_pool_not_expanded_at_per_agent_cap(mock_spawn: AsyncMock, mock_runtime: MagicMock) -> None:
    mock_runtime.sandbox_pool_max_per_agent = 2
    mock_runtime.sandbox_pool_max_warm = 10
    mock_runtime.sandbox_boot_timeout_seconds = 30

    agent = AgentFactory()
    cutoff = timezone.now() - timedelta(minutes=30)
    for _ in range(8):
        RunFactory(agent=agent, workspace=agent.workspace, created_at=cutoff)

    # Already at per-agent cap
    for _ in range(2):
        SandboxInstanceFactory(
            paused=True,
            agent=agent,
            workspace=agent.workspace,
        )

    count = pre_warm_pools()

    assert count == 0
    mock_spawn.assert_not_awaited()


@patch("apps.runs.tasks.pre_warm.runtime")
@patch("apps.runs.tasks.pre_warm.e2b.spawn_sandbox", new_callable=AsyncMock)
def test_pool_not_expanded_at_global_warm_cap(
    mock_spawn: AsyncMock, mock_runtime: MagicMock
) -> None:
    mock_runtime.sandbox_pool_max_per_agent = 5
    mock_runtime.sandbox_pool_max_warm = 1
    mock_runtime.sandbox_boot_timeout_seconds = 30

    agent = AgentFactory()
    cutoff = timezone.now() - timedelta(minutes=30)
    for _ in range(4):
        RunFactory(agent=agent, workspace=agent.workspace, created_at=cutoff)

    # One warm sandbox already consumes the global cap
    SandboxInstanceFactory(paused=True, workspace=agent.workspace)

    count = pre_warm_pools()

    assert count == 0
    mock_spawn.assert_not_awaited()
