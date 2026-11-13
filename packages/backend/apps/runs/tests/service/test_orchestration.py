"""Tests for run orchestration service layer."""

from __future__ import annotations

import os

import pytest
from asgiref.sync import sync_to_async

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.runs.factories import ConversationFactory, RunFactory, SandboxInstanceFactory
from apps.runs.models import Run, RunManifestRecord
from apps.runs.schemas.events import RunStatus
from apps.runs.services.orchestrator import refresh_sandbox_token, start_run, wake_for_run
from apps.runs.tests.conftest import (
    patched_e2b_env,
    patched_signing,
    setup_run_env,
)

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

pytestmark = pytest.mark.django_db(transaction=True)


# =====================================================================
# Service-layer tests
# =====================================================================


async def test_start_run_happy_path_result() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()
    with patched_e2b_env() as mocks:
        result = await start_run(
            workspace=ws,
            agent=agent,
            end_user=eu,
            prompt="Hello world",
        )
    assert result.run_id is not None
    assert result.run_uid is not None
    assert result.sandbox_url is not None
    assert result.capability_token is not None
    assert result.token_expires_at is not None
    mocks["post_manifest"].assert_awaited_once()
    mocks["spawn"].assert_awaited_once()


async def test_start_run_happy_path_db_state() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()
    with patched_e2b_env():
        result = await start_run(
            workspace=ws,
            agent=agent,
            end_user=eu,
            prompt="Check DB",
        )
    run = await sync_to_async(Run.objects.get)(pk=result.run_id)
    assert run.status == RunStatus.QUEUED
    assert run.prompt == "Check DB"
    assert run.workspace_id == ws.pk
    assert run.agent_id == agent.pk
    assert run.manifest_id is not None
    hold = await sync_to_async(BillingHold.objects.get)(run=run)
    assert hold.status == HoldStatus.ACTIVE
    assert hold.amount_reserved_usd > 0
    record = await sync_to_async(RunManifestRecord.objects.get)(run=run)
    assert record.sandbox_id == "sbx-test-001"


async def test_start_run_creates_conversation() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()
    with patched_e2b_env():
        result = await start_run(
            workspace=ws,
            agent=agent,
            end_user=eu,
            prompt="Multi-turn",
        )
    run = await sync_to_async(
        Run.objects.select_related("conversation").get,
    )(pk=result.run_id)
    assert run.conversation is not None
    assert run.conversation.workspace_id == ws.pk


async def test_start_run_insufficient_credits() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)(credits=0)
    from apps.core.exceptions import QuotaExceeded  # noqa: PLC0415

    with patched_e2b_env() as mocks, pytest.raises(QuotaExceeded):
        await start_run(workspace=ws, agent=agent, end_user=eu, prompt="Test")
    mocks["spawn"].assert_not_awaited()
    assert await sync_to_async(Run.objects.count)() == 0


async def test_start_run_concurrency_cap() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()

    def _create_active_run_and_set_cap():
        RunFactory(workspace=ws, agent=agent, end_user=eu, running=True)
        eu.profile.concurrency_max = 1
        eu.profile.save(update_fields=("concurrency_max",))

    await sync_to_async(_create_active_run_and_set_cap)()
    from apps.core.exceptions import QuotaExceeded  # noqa: PLC0415

    with patched_e2b_env() as mocks, pytest.raises(QuotaExceeded):
        await start_run(workspace=ws, agent=agent, end_user=eu, prompt="Test")
    mocks["spawn"].assert_not_awaited()


async def test_start_run_no_wallet_credits() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)(wallet_balance=None)
    from apps.core.exceptions import BillingError  # noqa: PLC0415

    with patched_e2b_env() as mocks, pytest.raises(BillingError):
        await start_run(workspace=ws, agent=agent, end_user=eu, prompt="Test")
    mocks["spawn"].assert_not_awaited()


async def test_start_run_rollback_on_post_failure() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()
    from apps.core.exceptions import SandboxError  # noqa: PLC0415

    with patched_e2b_env() as mocks:
        mocks["post_manifest"].side_effect = SandboxError("Post failed")
        with pytest.raises(SandboxError):
            await start_run(workspace=ws, agent=agent, end_user=eu, prompt="Test")
    mocks["spawn"].assert_awaited_once()
    active = BillingHold.objects.filter(status=HoldStatus.ACTIVE).count
    assert await sync_to_async(active)() == 0


async def test_wake_for_run_paused_sandbox() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()

    def _create():
        conv = ConversationFactory(workspace=ws, agent=agent, end_user=eu)
        run = RunFactory(
            workspace=ws,
            agent=agent,
            end_user=eu,
            running=True,
            conversation=conv,
        )
        SandboxInstanceFactory(
            paused=True,
            workspace=ws,
            agent=agent,
            conversation_id=conv.conversation_uid,
        )
        return run

    run = await sync_to_async(_create)()
    with patched_e2b_env() as mocks:
        result = await wake_for_run(workspace=ws, run=run)
    assert result.sandbox_url is not None
    assert result.capability_token is not None
    mocks["resume"].assert_awaited_once()


async def test_wake_for_run_no_sandbox() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()

    def _create():
        conv = ConversationFactory(workspace=ws, agent=agent, end_user=eu)
        return RunFactory(
            workspace=ws,
            agent=agent,
            end_user=eu,
            running=True,
            conversation=conv,
        )

    run = await sync_to_async(_create)()
    from apps.core.exceptions import NotFound  # noqa: PLC0415

    with patched_e2b_env(), pytest.raises(NotFound):
        await wake_for_run(workspace=ws, run=run)


async def test_wake_for_run_terminal_run() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()
    run = await sync_to_async(RunFactory)(
        workspace=ws,
        agent=agent,
        end_user=eu,
        finished=True,
    )
    from apps.core.exceptions import Conflict  # noqa: PLC0415

    with patched_e2b_env(), pytest.raises(Conflict):
        await wake_for_run(workspace=ws, run=run)


async def test_wake_for_run_no_conversation() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()
    run = await sync_to_async(RunFactory)(
        workspace=ws,
        agent=agent,
        end_user=eu,
        running=True,
    )
    from apps.core.exceptions import Conflict  # noqa: PLC0415

    with patched_e2b_env(), pytest.raises(Conflict):
        await wake_for_run(workspace=ws, run=run)


async def test_refresh_token_active_run() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()

    def _create():
        run = RunFactory(
            workspace=ws,
            agent=agent,
            end_user=eu,
            running=True,
            sandbox_id="sbx-active",
        )
        SandboxInstanceFactory(
            running=True,
            sandbox_id="sbx-active",
            workspace=ws,
            agent=agent,
        )
        return run

    run = await sync_to_async(_create)()
    with patched_signing():
        result = await sync_to_async(refresh_sandbox_token)(run=run)
    assert result.capability_token is not None
    assert result.token_expires_at is not None


async def test_refresh_token_terminal_run() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()

    def _create():
        run = RunFactory(
            workspace=ws,
            agent=agent,
            end_user=eu,
            finished=True,
            sandbox_id="sbx-dead",
        )
        SandboxInstanceFactory(
            running=True,
            sandbox_id="sbx-dead",
            workspace=ws,
            agent=agent,
        )
        return run

    run = await sync_to_async(_create)()
    from apps.core.exceptions import Conflict  # noqa: PLC0415

    with patched_signing(), pytest.raises(Conflict):
        await sync_to_async(refresh_sandbox_token)(run=run)


async def test_refresh_token_no_sandbox() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()
    run = await sync_to_async(RunFactory)(
        workspace=ws,
        agent=agent,
        end_user=eu,
        running=True,
        sandbox_id="sbx-gone",
    )
    from apps.core.exceptions import NotFound  # noqa: PLC0415

    with patched_signing(), pytest.raises(NotFound):
        await sync_to_async(refresh_sandbox_token)(run=run)
