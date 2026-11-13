"""Atomic DB record creation for a new run.

Called inside ``transaction.atomic`` by the orchestrator. Creates
Conversation, Run, BillingHold, signed manifest, and RunManifestRecord
in one transaction.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.billing.models.hold import BillingHold
from apps.runs.models.conversation import Conversation
from apps.runs.models.records import RunManifestRecord
from apps.runs.models.run import Run
from apps.runs.services.manifest import (
    ManifestInput,
    ManifestKnowledge,
    ManifestLease,
    ManifestTool,
    SignedManifest,
    build_manifest,
    sign_manifest,
)
from config.runtime import runtime

if TYPE_CHECKING:
    from datetime import datetime

    from apps.agents.models import Agent
    from apps.end_users.models import EndUser
    from apps.knowledge.models import Knowledge
    from apps.runs.models.sandbox_instance import SandboxInstance
    from apps.runs.schemas.lease import Lease
    from apps.tools.models import Tool
    from apps.workspaces.models import Workspace


def create_run_records(
    *,
    workspace: Workspace,
    agent: Agent,
    end_user: EndUser,
    prompt: str,
    conversation_uid: uuid.UUID | None,
    lease: Lease,
    instance: SandboxInstance,
    tools: list[Tool],
    knowledge: list[Knowledge],
    model_tier: str,
    hitl_mode: str = "interactive",
    is_scheduled: bool = False,
) -> tuple[Run, bytes]:
    """Create all run-related rows atomically; return Run + signed manifest."""
    with transaction.atomic():
        conv = _get_or_create_conversation(
            workspace,
            agent,
            end_user,
            conversation_uid,
        )
        run = _create_run(
            workspace,
            agent,
            end_user,
            prompt,
            conv,
            instance,
            lease,
            is_scheduled,
        )
        hold_expiry = timezone.now() + timedelta(
            seconds=lease.max_runtime_seconds + 300,
        )
        _create_hold(run, workspace, lease, hold_expiry)
        signed = _sign_and_record_manifest(
            run,
            instance,
            conv,
            agent,
            end_user,
            prompt,
            lease,
            model_tier,
            tools,
            knowledge,
            hold_expiry,
            hitl_mode,
        )
        _link_manifest_to_run(run, signed.manifest_id, instance)
        return run, signed.body


def _get_or_create_conversation(
    workspace: Workspace,
    agent: Agent,
    end_user: EndUser,
    conversation_uid: uuid.UUID | None,
) -> Conversation:
    if conversation_uid:
        try:
            return Conversation.objects.get(
                conversation_uid=conversation_uid,
                workspace=workspace,
            )
        except Conversation.DoesNotExist:
            pass
    return Conversation.objects.create(
        workspace=workspace,
        agent=agent,
        end_user=end_user,
    )


def _create_run(
    workspace: Workspace,
    agent: Agent,
    end_user: EndUser,
    prompt: str,
    conv: Conversation,
    instance: SandboxInstance,
    lease: Lease,
    is_scheduled: bool,
) -> Run:
    return Run.objects.create(
        workspace=workspace,
        agent=agent,
        end_user=end_user,
        prompt=prompt,
        conversation=conv,
        status="queued",
        sandbox_id=instance.sandbox_id,
        lease_json=lease.model_dump(mode="json"),
        is_scheduled=is_scheduled,
    )


def _create_hold(
    run: Run,
    workspace: Workspace,
    lease: Lease,
    hold_expiry: datetime,
) -> None:
    BillingHold.objects.create(
        run=run,
        wallet=workspace.wallet,
        amount_reserved_usd=lease.max_cost_usd,
        expires_at=hold_expiry,
    )


def _sign_and_record_manifest(
    run: Run,
    instance: SandboxInstance,
    conv: Conversation,
    agent: Agent,
    end_user: EndUser,
    prompt: str,
    lease: Lease,
    model_tier: str,
    tools: list[Tool],
    knowledge: list[Knowledge],
    hold_expiry: datetime,
    hitl_mode: str,
) -> SignedManifest:
    callback_auth = os.urandom(runtime.callback_hmac_secret_length)
    callback_url = f"{runtime.backend_public_url}{runtime.callback_ingestion_path}"
    manifest_input = _build_manifest_input(
        run,
        instance,
        conv,
        agent,
        end_user,
        prompt,
        lease,
        model_tier,
        tools,
        knowledge,
        callback_url,
        callback_auth,
        hitl_mode,
    )
    signed = sign_manifest(build_manifest(manifest_input))
    _persist_manifest_record(
        run,
        instance,
        signed,
        callback_auth,
        hold_expiry,
    )
    return signed


def _persist_manifest_record(
    run: Run,
    instance: SandboxInstance,
    signed: SignedManifest,
    callback_auth: bytes,
    hold_expiry: datetime,
) -> None:
    RunManifestRecord.objects.create(
        manifest_id=uuid.UUID(signed.manifest_id),
        run=run,
        sandbox_id=instance.sandbox_id,
        signing_key_id=runtime.midsphere_manifest_key_id,
        manifest_hash=signed.manifest_hash,
        callback_auth_encrypted=RunManifestRecord.encrypt_callback_auth(
            callback_auth,
        ),
        expires_at=hold_expiry,
    )


def _link_manifest_to_run(
    run: Run,
    manifest_id: str,
    instance: SandboxInstance,
) -> None:
    run.manifest_id = uuid.UUID(manifest_id)
    run.save(update_fields=("manifest_id", "updated_at"))
    instance.current_run = run
    instance.save(update_fields=("current_run", "updated_at"))


def _build_manifest_input(
    run: Run,
    instance: SandboxInstance,
    conv: Conversation,
    agent: Agent,
    end_user: EndUser,
    prompt: str,
    lease: Lease,
    model_tier: str,
    tools: list[Tool],
    knowledge: list[Knowledge],
    callback_url: str,
    callback_auth: bytes,
    hitl_mode: str,
) -> ManifestInput:
    return ManifestInput(
        run_id=run.run_uid,
        sandbox_id=instance.sandbox_id,
        workspace_id=run.workspace_id,
        agent_id=agent.pk,
        end_user_id=end_user.pk,
        conversation_id=conv.conversation_uid,
        prompt=prompt,
        system_prompt=agent.system_prompt,
        policy_block=_resolve_policy_block(agent),
        lease=ManifestLease(
            max_runtime_seconds=lease.max_runtime_seconds,
            max_total_tokens=lease.max_total_tokens,
            max_cost_usd=lease.max_cost_usd,
        ),
        model_tier=model_tier,
        hitl_mode=hitl_mode,
        tools=_serialize_tools(tools),
        knowledge=_serialize_knowledge(knowledge),
        callback_url=callback_url,
        callback_auth=callback_auth.hex(),
    )


def _resolve_policy_block(agent: Agent) -> str:
    policies = agent.effective_policies()
    return "\n".join(p.as_system_prompt_block() for p in policies)


def _serialize_tools(tools: list[Tool]) -> tuple[ManifestTool, ...]:
    return tuple(
        ManifestTool(
            id=t.pk,
            name=t.name,
            description=t.description,
            parameters_schema=t.parameters_schema,
            execution_endpoint=t.execution_endpoint,
            is_sensitive=t.is_sensitive,
        )
        for t in tools
    )


def _serialize_knowledge(
    knowledge: list[Knowledge],
) -> tuple[ManifestKnowledge, ...]:
    return tuple(
        ManifestKnowledge(
            id=kb.pk,
            name=kb.name,
            kind=kb.kind,
            source=kb.source_endpoint or "",
        )
        for kb in knowledge
    )
