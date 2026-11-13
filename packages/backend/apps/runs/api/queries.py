from __future__ import annotations

import uuid

import strawberry
import strawberry_django
from strawberry import relay
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.runs.api.types import ConversationType, RatingStats, RatingType, RunType, ScoreBucket
from apps.runs.models import Conversation, Rating, Run


def _run_lookup(id: strawberry.ID) -> tuple[int | None, uuid.UUID | None] | None:
    raw = str(id)
    try:
        global_id = relay.GlobalID.from_id(raw)
    except ValueError:
        return _raw_run_lookup(raw)
    if global_id.type_name != "RunType":
        return None
    return _raw_pk_lookup(global_id.node_id)


def _raw_run_lookup(raw: str) -> tuple[int | None, uuid.UUID | None] | None:
    if raw.isdecimal():
        return _raw_pk_lookup(raw)
    try:
        return None, uuid.UUID(raw)
    except ValueError:
        return None


def _raw_pk_lookup(raw: str) -> tuple[int | None, uuid.UUID | None] | None:
    return (int(raw), None) if raw.isdecimal() else None


@strawberry.type
class RunQuery:
    @strawberry_django.connection(DjangoListConnection[RunType])
    @workspace_scoped
    @requires_role(Action.RUNS_READ)
    @requires_scope("runs:read")
    def runs(
        self,
        info: Info,
        status: str | None = None,
        agent_id: int | None = None,
        end_user_id: int | None = None,
    ) -> list[Run]:
        return Run.list_for_workspace(  # type: ignore[return-value]
            info.context.workspace.pk,
            status=status,
            agent_id=agent_id,
            end_user_id=end_user_id,
        )

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.RUNS_READ)
    @requires_scope("runs:read")
    def run(
        self,
        info: Info,
        id: strawberry.ID | None = None,
        run_uid: uuid.UUID | None = None,
    ) -> RunType | None:
        if id is not None:
            return _get_run_by_lookup(info.context.workspace.pk, id)  # type: ignore[return-value]
        if run_uid is None:
            return None
        return Run.get_by_uid(info.context.workspace.pk, run_uid)  # type: ignore[return-value]

    @strawberry_django.connection(DjangoListConnection[ConversationType])
    @workspace_scoped
    @requires_role(Action.RUNS_READ)
    @requires_scope("runs:read")
    def conversations(
        self,
        info: Info,
        agent_id: int | None = None,
    ) -> list[Conversation]:
        return Conversation.list_for_workspace(  # type: ignore[return-value]
            info.context.workspace.pk,
            agent_id=agent_id,
        )

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.RUNS_READ)
    @requires_scope("runs:read")
    def conversation(
        self,
        info: Info,
        id: strawberry.ID | None = None,
        conversation_uid: uuid.UUID | None = None,
    ) -> ConversationType | None:
        ws_id = info.context.workspace.pk
        if id is not None:
            pk = parse_int_id(id, expected_type="ConversationType", field="id")
            return Conversation.get_for_workspace(ws_id, pk)  # type: ignore[return-value]
        if conversation_uid is not None:
            return Conversation.get_by_uid(ws_id, conversation_uid)  # type: ignore[return-value]
        return None


def _get_run_by_lookup(workspace_id: int, id: strawberry.ID) -> Run | None:
    lookup = _run_lookup(id)
    if lookup is None:
        return None
    pk, run_uid = lookup
    if pk is not None:
        return Run.get_for_workspace(workspace_id, pk)
    if run_uid is not None:
        return Run.get_by_uid(workspace_id, run_uid)
    return None


@strawberry.type
class RatingQuery:
    @strawberry.field
    @workspace_scoped
    @requires_role(Action.RATINGS_READ)
    @requires_scope("runs:read")
    def rating_for_run(self, info: Info, run_uid: uuid.UUID) -> RatingType | None:
        return Rating.get_for_run_uid(  # type: ignore[return-value]
            info.context.workspace.pk, run_uid
        )

    @strawberry_django.connection(DjangoListConnection[RatingType])
    @workspace_scoped
    @requires_role(Action.RATINGS_READ)
    @requires_scope("runs:read")
    def ratings(self, info: Info, agent_id: int | None = None) -> list[Rating]:
        return Rating.list_for_workspace(  # type: ignore[return-value]
            info.context.workspace.pk,
            agent_id=agent_id,
        )

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.RATINGS_READ)
    @requires_scope("runs:read")
    def rating_stats(
        self,
        info: Info,
        agent_id: int | None = None,
    ) -> RatingStats:
        stats = Rating.stats_for_workspace(info.context.workspace.pk, agent_id=agent_id)
        return RatingStats(
            average=stats["average"],
            total_count=stats["total_count"],
            distribution=[ScoreBucket(score=s, count=c) for s, c in stats["distribution"]],
        )
