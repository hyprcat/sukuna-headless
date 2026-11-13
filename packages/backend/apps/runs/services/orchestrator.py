"""Run orchestration — startRun, wakeForRun, refreshSandboxToken.

Cross-aggregate service: ties together the sandbox pool, manifest builder,
JWT minter, billing hold, conversation, and run models. Async because the
E2B SDK is natively async.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from asgiref.sync import sync_to_async

from apps.billing.models.hold import BillingHold
from apps.core.events import record_event
from apps.core.exceptions import BillingError, Conflict, NotFound, QuotaExceeded
from apps.runs.models.run import Run
from apps.runs.models.sandbox_instance import SandboxInstance, SandboxState
from apps.runs.schemas.lease import Lease
from apps.runs.schemas.orchestration import (
    DenialMessages,
    RefreshTokenResult,
    RunOrchestrationDefaults,
    StartRunResult,
    WakeForRunResult,
)
from apps.runs.services import sandbox_pool
from apps.runs.services.capability_token import (
    mint_capability_token,
    refresh_capability_token,
)
from apps.runs.services.run_records import create_run_records
from config.runtime import runtime
from integrations import e2b

if TYPE_CHECKING:
    from datetime import datetime

    from apps.agents.models import Agent
    from apps.end_users.models import EndUser
    from apps.knowledge.models import Knowledge
    from apps.tools.models import Tool
    from apps.workspaces.models import Workspace

_log = structlog.get_logger(__name__)
_DEFAULTS = RunOrchestrationDefaults()
_DENIALS = DenialMessages()


async def start_run(
    *,
    workspace: Workspace,
    agent: Agent,
    end_user: EndUser,
    prompt: str,
    conversation_uid: uuid.UUID | None = None,
    tools: list[Tool] | None = None,
    knowledge: list[Knowledge] | None = None,
) -> StartRunResult:
    """Full startRun flow: check -> acquire -> create -> post -> mint."""
    tools = tools or []
    knowledge = knowledge or []
    model_tier = await sync_to_async(_check_can_run)(end_user, agent, tools, knowledge)

    run, instance = await provision_run(
        workspace=workspace,
        agent=agent,
        end_user=end_user,
        prompt=prompt,
        model_tier=model_tier,
        tools=tools,
        knowledge=knowledge,
        conversation_uid=conversation_uid,
    )

    token, expires_at = await sync_to_async(_mint_token)(run, instance)
    _emit_start_event(run)
    url = _sandbox_stream_url(instance)
    return StartRunResult(
        run_id=run.pk,
        run_uid=run.run_uid,
        sandbox_url=url,
        capability_token=token,
        token_expires_at=expires_at,
    )


async def provision_run(
    *,
    workspace: Workspace,
    agent: Agent,
    end_user: EndUser,
    prompt: str,
    model_tier: str,
    tools: list[Tool],
    knowledge: list[Knowledge],
    conversation_uid: uuid.UUID | None = None,
    hitl_mode: str = "interactive",
    is_scheduled: bool = False,
) -> tuple[Run, SandboxInstance]:
    """Acquire a sandbox, create run records, and post the signed manifest.

    Shared by ``start_run`` and the schedule dispatcher. Rolls the sandbox and
    hold back on any failure after acquisition.
    """
    lease = await sync_to_async(_compute_lease)(end_user, workspace)
    instance = await sandbox_pool.acquire_sandbox(agent, workspace, conversation_uid)
    try:
        await e2b.set_sandbox_timeout(instance.sandbox_id, lease.max_runtime_seconds)
        run, manifest_body = await sync_to_async(create_run_records)(
            workspace=workspace,
            agent=agent,
            end_user=end_user,
            prompt=prompt,
            conversation_uid=conversation_uid,
            lease=lease,
            instance=instance,
            tools=tools,
            knowledge=knowledge,
            model_tier=model_tier,
            hitl_mode=hitl_mode,
            is_scheduled=is_scheduled,
        )
    except Exception:
        await _rollback_sandbox(instance)
        raise
    try:
        await e2b.post_manifest(instance.sandbox_id, manifest_body)
    except Exception:
        await _rollback_sandbox(instance)
        await sync_to_async(_release_hold)(run)
        raise
    return run, instance


def _check_can_run(
    end_user: EndUser,
    agent: Agent,
    tools: list[Tool],
    knowledge: list[Knowledge],
) -> str:
    from apps.core.errors import UserError  # noqa: PLC0415
    from apps.end_users.schemas import Denied  # noqa: PLC0415

    active = Run.objects.active_count_for_end_user(end_user.pk)
    check = end_user.check_can_run(
        agent,
        tools,
        knowledge,
        active_run_count=active,
    )
    if isinstance(check, Denied):
        msg = getattr(_DENIALS, str(check.reason).lower(), _DENIALS.fallback)
        if check.reason == UserError.BILLING_ERROR:
            raise BillingError(msg)
        raise QuotaExceeded(check.reason, msg)
    return check.model_tier


async def wake_for_run(
    *,
    workspace: Workspace,
    run: Run,
) -> WakeForRunResult:
    """Resume a paused sandbox for multi-turn conversation."""
    conv_uid = await sync_to_async(_validate_wakeable)(run)
    instance = await sync_to_async(_find_paused_sandbox)(conv_uid)
    if instance is None:
        raise NotFound("No paused sandbox found for this conversation.")

    ttl = runtime.sandbox_resume_timeout_seconds
    handle = await e2b.resume_sandbox(
        instance.sandbox_id,
        ttl_seconds=ttl,
    )
    await sync_to_async(_mark_sandbox_running)(instance, run)

    token, expires_at = await sync_to_async(_mint_token)(run, instance)
    return WakeForRunResult(
        sandbox_url=handle.sandbox_url,
        capability_token=token,
        token_expires_at=expires_at,
    )


def refresh_sandbox_token(*, run: Run) -> RefreshTokenResult:
    """Mint a fresh capability JWT for an active run."""
    instance = _get_running_sandbox(run)
    token, expires_at = refresh_capability_token(
        run_id=run.run_uid,
        sandbox_id=instance.sandbox_id,
        workspace_id=run.workspace_id,
        end_user_id=run.end_user_id,
        conversation_id=_conversation_uid(run),
        is_terminal=run.is_terminal,
        scopes=list(_DEFAULTS.scopes),
    )
    return RefreshTokenResult(
        capability_token=token,
        token_expires_at=expires_at,
    )


def _compute_lease(
    end_user: EndUser,
    workspace: Workspace,
) -> Lease:
    profile = end_user.profile
    max_runtime = profile.sandbox_time_seconds or _DEFAULTS.max_runtime_seconds
    available = workspace.wallet.available()
    max_cost = min(available, _DEFAULTS.max_cost_usd)
    if max_cost <= 0:
        raise BillingError("Workspace has no available credits.")
    return Lease(
        max_runtime_seconds=max_runtime,
        max_total_tokens=_DEFAULTS.max_total_tokens,
        max_cost_usd=max_cost,
    )


def _sandbox_stream_url(instance: SandboxInstance) -> str:
    # Production fronts sandboxes behind a wildcard proxy (sandbox_domain). When
    # it's unset (local dev) the SDK streams straight from the E2B host.
    if runtime.sandbox_domain:
        return f"https://{instance.sandbox_id}.{runtime.sandbox_domain}"
    return instance.sandbox_url


def _mint_token(
    run: Run,
    instance: SandboxInstance,
) -> tuple[str, datetime]:
    return mint_capability_token(
        run_id=run.run_uid,
        sandbox_id=instance.sandbox_id,
        workspace_id=run.workspace_id,
        end_user_id=run.end_user_id,
        conversation_id=_conversation_uid(run),
        scopes=list(_DEFAULTS.scopes),
    )


def _conversation_uid(run: Run) -> uuid.UUID:
    conv = run.conversation
    if conv is not None:
        return conv.conversation_uid
    return uuid.UUID(int=0)


def _validate_wakeable(run: Run) -> uuid.UUID:
    if run.is_terminal:
        raise Conflict("Run is already terminal.")
    conv = run.conversation
    if conv is None:
        raise Conflict("Run has no conversation for multi-turn wake.")
    return conv.conversation_uid


def _find_paused_sandbox(
    conversation_uid: uuid.UUID,
) -> SandboxInstance | None:
    from django.db import transaction  # noqa: PLC0415

    with transaction.atomic():
        return (
            SandboxInstance.objects.filter(
                conversation_id=conversation_uid,
                sandbox_state=SandboxState.PAUSED,
            )
            .select_for_update(skip_locked=True)
            .first()
        )


def _mark_sandbox_running(
    instance: SandboxInstance,
    run: Run,
) -> None:
    instance.sandbox_state = SandboxState.RUNNING
    instance.current_run = run
    instance.resume_count += 1
    instance.save(
        update_fields=(
            "sandbox_state",
            "current_run",
            "resume_count",
            "updated_at",
        ),
    )


def _get_running_sandbox(run: Run) -> SandboxInstance:
    try:
        return SandboxInstance.objects.get(
            sandbox_id=run.sandbox_id,
            sandbox_state__in=(
                SandboxState.RUNNING,
                SandboxState.BOOTING,
            ),
        )
    except SandboxInstance.DoesNotExist as exc:
        raise NotFound("No active sandbox for this run.") from exc


def _release_hold(run: Run) -> None:
    try:
        hold = BillingHold.objects.get(run=run)
        hold.release()
    except BillingHold.DoesNotExist:
        pass


async def _rollback_sandbox(instance: SandboxInstance) -> None:
    try:
        await sandbox_pool.release_sandbox(instance)
    except Exception:
        _log.warning(
            "sandbox_rollback_failed",
            sandbox_id=instance.sandbox_id,
            exc_info=True,
        )


def _emit_start_event(run: Run) -> None:
    record_event(
        "run_queued",
        distinct_id=str(run.workspace_id),
        properties={
            "run_id": str(run.run_uid),
            "agent_id": str(run.agent_id),
            "end_user_id": str(run.end_user_id),
        },
    )
