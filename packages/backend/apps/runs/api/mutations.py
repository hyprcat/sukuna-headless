from __future__ import annotations

import uuid

import strawberry
from asgiref.sync import async_to_sync
from strawberry import relay
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.agents.models import Agent
from apps.core.api.ids import parse_int_id, parse_int_ids
from apps.core.api.mappers import catch_domain_errors
from apps.core.api.types import UserErrorType
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.core.exceptions import DomainError, NotFound
from apps.end_users.models import EndUser
from apps.knowledge.models import Knowledge
from apps.runs.api.types import (
    RefreshTokenPayload,
    StartRunPayload,
    SubmitRatingPayload,
    WakeForRunPayload,
)
from apps.runs.models import Rating, Run
from apps.runs.schemas.orchestration import StartRunResult
from apps.tools.models import Tool


@strawberry.input
class SubmitRatingInput:
    run_id: uuid.UUID
    score: int
    comment: str = ""


@strawberry.input
class StartRunInput:
    agent_id: strawberry.ID
    end_user_id: strawberry.ID
    prompt: str
    conversation_uid: uuid.UUID | None = None
    tool_ids: list[strawberry.ID] | None = None
    knowledge_ids: list[strawberry.ID] | None = None


@strawberry.type
class RatingMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_scope("runs:write")
    @catch_domain_errors(SubmitRatingPayload)
    def submit_rating(self, info: Info, input: SubmitRatingInput) -> SubmitRatingPayload:
        rating = Rating.submit_by_uid(
            run_uid=input.run_id,
            score=input.score,
            comment=input.comment,
        )
        return SubmitRatingPayload(
            success=True,
            errors=[],
            rating=rating,  # type: ignore[arg-type]
        )


@strawberry.type
class RunMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.RUNS_WRITE)
    @requires_scope("runs:write")
    def start_run(self, info: Info, input: StartRunInput) -> StartRunPayload:
        # Sync resolver bridging to the async orchestrator: the GraphQL view is
        # sync (most resolvers do direct ORM), so async work crosses via
        # async_to_sync rather than making the whole schema async.
        from apps.runs.services.orchestrator import start_run  # noqa: PLC0415

        ws = info.context.workspace
        try:
            agent, end_user, tools, knowledge = _resolve_run_inputs(ws.pk, input)
            result = async_to_sync(start_run)(
                workspace=ws,
                agent=agent,
                end_user=end_user,
                prompt=input.prompt,
                conversation_uid=input.conversation_uid,
                tools=tools,
                knowledge=knowledge,
            )
        except DomainError as exc:
            return StartRunPayload(success=False, errors=[UserErrorType.from_domain(exc)])
        return _start_run_payload(result)

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.RUNS_WRITE)
    @requires_scope("runs:write")
    def wake_for_run(self, info: Info, run_id: strawberry.ID) -> WakeForRunPayload:
        from apps.runs.services.orchestrator import wake_for_run  # noqa: PLC0415

        ws = info.context.workspace
        try:
            run = _resolve_run(ws.pk, run_id)
            result = async_to_sync(wake_for_run)(workspace=ws, run=run)
        except DomainError as exc:
            return WakeForRunPayload(success=False, errors=[UserErrorType.from_domain(exc)])

        return WakeForRunPayload(
            success=True,
            errors=[],
            sandbox_url=result.sandbox_url,
            capability_token=result.capability_token,
            token_expires_at=result.token_expires_at,
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.RUNS_WRITE)
    @requires_scope("runs:write")
    def refresh_sandbox_token(self, info: Info, run_id: strawberry.ID) -> RefreshTokenPayload:
        from apps.runs.services.orchestrator import refresh_sandbox_token  # noqa: PLC0415

        ws = info.context.workspace
        try:
            run = _resolve_run(ws.pk, run_id)
            result = refresh_sandbox_token(run=run)
        except DomainError as exc:
            return RefreshTokenPayload(success=False, errors=[UserErrorType.from_domain(exc)])

        return RefreshTokenPayload(
            success=True,
            errors=[],
            capability_token=result.capability_token,
            token_expires_at=result.token_expires_at,
        )


def _resolve_run_inputs(
    workspace_pk: int,
    input: StartRunInput,
) -> tuple[Agent, EndUser, list[Tool], list[Knowledge]]:
    return (
        _resolve_agent(workspace_pk, input.agent_id),
        _resolve_end_user(workspace_pk, input.end_user_id),
        _resolve_tools(workspace_pk, input.tool_ids),
        _resolve_knowledge(workspace_pk, input.knowledge_ids),
    )


def _start_run_payload(result: StartRunResult) -> StartRunPayload:
    return StartRunPayload(
        success=True,
        errors=[],
        run_id=strawberry.ID(relay.to_base64("RunType", result.run_id)),
        run_uid=result.run_uid,
        sandbox_url=result.sandbox_url,
        capability_token=result.capability_token,
        token_expires_at=result.token_expires_at,
    )


def _resolve_agent(workspace_pk: int, agent_id: strawberry.ID) -> Agent:
    pk = parse_int_id(agent_id, expected_type="AgentType", field="agent_id")
    agent = Agent.objects.filter(pk=pk, workspace_id=workspace_pk, is_active=True).first()
    if agent is None:
        raise NotFound("Agent not found or inactive.")
    return agent


def _resolve_end_user(workspace_pk: int, end_user_id: strawberry.ID) -> EndUser:
    pk = parse_int_id(end_user_id, expected_type="EndUserType", field="end_user_id")
    eu = EndUser.get_for_workspace(workspace_pk, pk)
    if eu is None:
        raise NotFound("End user not found.")
    return eu


def _resolve_tools(workspace_pk: int, tool_ids: list[strawberry.ID] | None) -> list[Tool]:
    if not tool_ids:
        return []
    pks = parse_int_ids(tool_ids, expected_type="ToolType", field="tool_ids")
    tools = list(Tool.objects.filter(pk__in=pks, workspace_id=workspace_pk, is_active=True))
    if len(tools) != len(pks):
        raise NotFound("One or more tools not found or inactive.")
    return tools


def _resolve_knowledge(
    workspace_pk: int,
    knowledge_ids: list[strawberry.ID] | None,
) -> list[Knowledge]:
    if not knowledge_ids:
        return []
    pks = parse_int_ids(knowledge_ids, expected_type="KnowledgeType", field="knowledge_ids")
    kbs = list(Knowledge.objects.filter(pk__in=pks, workspace_id=workspace_pk, is_active=True))
    if len(kbs) != len(pks):
        raise NotFound("One or more knowledge sources not found or inactive.")
    return kbs


def _resolve_run(workspace_pk: int, run_id: strawberry.ID) -> Run:
    pk = parse_int_id(run_id, expected_type="RunType", field="run_id")
    run = (
        Run.objects.select_related("conversation", "agent", "end_user")
        .filter(
            pk=pk,
            workspace_id=workspace_pk,
        )
        .first()
    )
    if run is None:
        raise NotFound("Run not found.")
    return run
