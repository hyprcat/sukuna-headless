from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.agents.factories import AgentFactory
from apps.core.exceptions import SandboxError
from apps.runs.factories import RunFactory, SandboxInstanceFactory
from apps.runs.models import SandboxState
from apps.runs.services.sandbox_pool import (
    acquire_sandbox,
    compute_target_pool_size,
    release_sandbox,
)
from integrations.e2b import SandboxHandle


def _handle() -> SandboxHandle:
    return SandboxHandle(sandbox_id="sbx-new-001", sandbox_url="https://sbx-new-001.e2b.app")


def _mock_e2b():
    return (
        patch("integrations.e2b.spawn_sandbox", new_callable=AsyncMock, return_value=_handle()),
        patch("integrations.e2b.resume_sandbox", new_callable=AsyncMock),
        patch("integrations.e2b.pause_sandbox", new_callable=AsyncMock),
        patch("integrations.e2b.terminate_sandbox", new_callable=AsyncMock),
    )


async def _sandbox(**kwargs):
    return await sync_to_async(SandboxInstanceFactory)(**kwargs)


async def _agent(**kwargs):
    return await sync_to_async(AgentFactory)(**kwargs)


# ---------------------------------------------------------------------------
# acquire_sandbox — conversation affinity
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_acquire_conversation_affinity() -> None:
    conv_uid = uuid.uuid4()
    warm = await _sandbox(paused=True, conversation_id=conv_uid)
    agent = warm.agent
    workspace = warm.workspace

    spawn_p, resume_p, *_ = _mock_e2b()
    with spawn_p as spawn, resume_p as resume:
        result = await acquire_sandbox(agent, workspace, conversation_id=conv_uid)

    assert result.pk == warm.pk
    spawn.assert_not_awaited()
    resume.assert_awaited_once_with(warm.sandbox_id, ttl_seconds=15)
    await sync_to_async(result.refresh_from_db)()
    assert result.sandbox_state == SandboxState.RUNNING
    assert result.resume_count == 1


@pytest.mark.django_db(transaction=True)
async def test_acquire_conversation_miss_falls_to_agent_pool() -> None:
    agent = await _agent()
    warm = await _sandbox(paused=True, agent=agent, workspace=agent.workspace)
    unrelated_conv = uuid.uuid4()

    spawn_p, resume_p, *_ = _mock_e2b()
    with spawn_p as spawn, resume_p as resume:
        result = await acquire_sandbox(agent, agent.workspace, conversation_id=unrelated_conv)

    assert result.pk == warm.pk
    spawn.assert_not_awaited()
    resume.assert_awaited_once_with(warm.sandbox_id, ttl_seconds=15)


@pytest.mark.django_db(transaction=True)
async def test_acquire_conversation_affinity_is_workspace_scoped() -> None:
    conv_uid = uuid.uuid4()
    foreign = await _sandbox(paused=True, conversation_id=conv_uid)
    agent = await _agent()

    spawn_p, resume_p, *_ = _mock_e2b()
    with spawn_p as spawn, resume_p as resume:
        result = await acquire_sandbox(agent, agent.workspace, conversation_id=conv_uid)

    assert result.sandbox_id == _handle().sandbox_id
    spawn.assert_awaited_once()
    resume.assert_not_awaited()
    await sync_to_async(foreign.refresh_from_db)()
    assert foreign.sandbox_state == SandboxState.PAUSED


# ---------------------------------------------------------------------------
# acquire_sandbox — warm pool (agent affinity)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_acquire_warm_pool() -> None:
    agent = await _agent()
    warm = await _sandbox(paused=True, agent=agent, workspace=agent.workspace)

    spawn_p, resume_p, *_ = _mock_e2b()
    with spawn_p as spawn, resume_p as resume:
        result = await acquire_sandbox(agent, agent.workspace)

    assert result.pk == warm.pk
    spawn.assert_not_awaited()
    resume.assert_awaited_once_with(warm.sandbox_id, ttl_seconds=15)
    await sync_to_async(result.refresh_from_db)()
    assert result.sandbox_state == SandboxState.RUNNING


# ---------------------------------------------------------------------------
# acquire_sandbox — fresh spawn
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_acquire_fresh_spawn_when_no_warm() -> None:
    agent = await _agent()

    spawn_p, resume_p, *_ = _mock_e2b()
    with spawn_p as spawn, resume_p as resume:
        result = await acquire_sandbox(agent, agent.workspace)

    spawn.assert_awaited_once()
    resume.assert_not_awaited()
    assert result.sandbox_id == _handle().sandbox_id
    assert result.sandbox_url == _handle().sandbox_url
    assert result.sandbox_state == SandboxState.BOOTING
    assert result.workspace == agent.workspace
    assert result.agent == agent
    assert result.boot_started_at is not None


@pytest.mark.django_db(transaction=True)
async def test_acquire_skips_running_sandbox() -> None:
    """Running sandboxes are not in the warm pool."""
    agent = await _agent()
    await _sandbox(running=True, agent=agent, workspace=agent.workspace)

    spawn_p, resume_p, *_ = _mock_e2b()
    with spawn_p as spawn, resume_p:
        result = await acquire_sandbox(agent, agent.workspace)

    spawn.assert_awaited_once()
    assert result.sandbox_id == _handle().sandbox_id


@pytest.mark.django_db(transaction=True)
async def test_acquire_terminates_stale_warm_and_spawns_fresh() -> None:
    agent = await _agent()
    stale = await _sandbox(paused=True, agent=agent, workspace=agent.workspace)

    spawn_p, resume_p, *_ = _mock_e2b()
    with spawn_p as spawn, resume_p as resume:
        resume.side_effect = SandboxError("resume failed")
        result = await acquire_sandbox(agent, agent.workspace)

    resume.assert_awaited_once_with(stale.sandbox_id, ttl_seconds=15)
    spawn.assert_awaited_once()
    assert result.sandbox_id == _handle().sandbox_id
    await sync_to_async(stale.refresh_from_db)()
    assert stale.sandbox_state == SandboxState.TERMINATED


# ---------------------------------------------------------------------------
# release_sandbox — pause vs terminate
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_release_pauses_when_under_caps() -> None:
    inst = await _sandbox(running=True)

    *_, pause_p, term_p = _mock_e2b()
    with pause_p as pause_mock, term_p as term_mock, _patch_pool_caps(max_per_agent=5, max_warm=10):
        await release_sandbox(inst)

    pause_mock.assert_awaited_once_with(inst.sandbox_id)
    term_mock.assert_not_awaited()
    await sync_to_async(inst.refresh_from_db)()
    assert inst.sandbox_state == SandboxState.PAUSED


@pytest.mark.django_db(transaction=True)
async def test_release_terminates_when_agent_cap_reached() -> None:
    agent = await _agent()
    inst = await _sandbox(running=True, agent=agent, workspace=agent.workspace)
    for _ in range(5):
        await _sandbox(paused=True, agent=agent, workspace=agent.workspace)

    *_, pause_p, term_p = _mock_e2b()
    with pause_p as pause_mock, term_p as term_mock, _patch_pool_caps(max_per_agent=5, max_warm=20):
        await release_sandbox(inst)

    term_mock.assert_awaited_once_with(inst.sandbox_id)
    pause_mock.assert_not_awaited()
    await sync_to_async(inst.refresh_from_db)()
    assert inst.sandbox_state == SandboxState.TERMINATED


@pytest.mark.django_db(transaction=True)
async def test_release_terminates_when_global_cap_reached() -> None:
    inst = await _sandbox(running=True)
    for _ in range(2):
        await _sandbox(paused=True)

    *_, pause_p, term_p = _mock_e2b()
    with pause_p as pause_mock, term_p as term_mock, _patch_pool_caps(max_per_agent=10, max_warm=2):
        await release_sandbox(inst)

    term_mock.assert_awaited_once_with(inst.sandbox_id)
    pause_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# concurrent acquire serialization
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_concurrent_acquire_only_one_wins() -> None:
    """Two sequential acquires on the same warm sandbox — first claims, second spawns."""
    agent = await _agent()
    await _sandbox(paused=True, agent=agent, workspace=agent.workspace)

    spawn_p, resume_p, *_ = _mock_e2b()
    with spawn_p as spawn, resume_p:
        r1 = await acquire_sandbox(agent, agent.workspace)
        r2 = await acquire_sandbox(agent, agent.workspace)

    assert r1.sandbox_state == SandboxState.RUNNING
    assert r2.sandbox_id == _handle().sandbox_id
    spawn.assert_awaited_once()


# ---------------------------------------------------------------------------
# compute_target_pool_size
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pool_size_zero_with_no_runs() -> None:
    agent = AgentFactory()
    assert compute_target_pool_size(agent) == 0


@pytest.mark.django_db
def test_pool_size_scales_with_runs() -> None:
    agent = AgentFactory()
    for _ in range(8):
        RunFactory(agent=agent, workspace=agent.workspace)

    assert compute_target_pool_size(agent) == 2  # ceil(8/4)


@pytest.mark.django_db
def test_pool_size_capped_at_max_per_agent() -> None:
    agent = AgentFactory()
    for _ in range(100):
        RunFactory(agent=agent, workspace=agent.workspace)

    with _patch_pool_caps(max_per_agent=3, max_warm=10):
        assert compute_target_pool_size(agent) == 3


@pytest.mark.django_db
def test_pool_size_ignores_old_runs() -> None:
    agent = AgentFactory()
    two_hours_ago = timezone.now() - timedelta(hours=2)
    for _ in range(10):
        r = RunFactory(agent=agent, workspace=agent.workspace)
        type(r).objects.filter(pk=r.pk).update(created_at=two_hours_ago)

    assert compute_target_pool_size(agent) == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_pool_caps(*, max_per_agent: int, max_warm: int):
    """Context manager to override runtime pool caps."""
    from apps.runs.services import sandbox_pool  # noqa: PLC0415

    return patch.multiple(
        sandbox_pool.runtime,
        sandbox_pool_max_per_agent=max_per_agent,
        sandbox_pool_max_warm=max_warm,
    )
