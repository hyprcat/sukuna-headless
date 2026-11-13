from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import cast

import strawberry
import strawberry_django
from django.core.exceptions import ObjectDoesNotExist
from strawberry import relay
from strawberry_django.relay import DjangoListConnection

from apps.core.api.types import MutationResult
from apps.runs.models import Conversation, Rating, Run, RunEvent
from apps.runs.schemas.events import RunStatus


@strawberry.enum
class RunStatusEnum(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


@strawberry_django.type(Rating)
class RatingType(relay.Node):
    score: int
    comment: str
    created_at: datetime

    @strawberry_django.field(select_related=["run"])
    def run_uid(self) -> uuid.UUID:
        return uuid.UUID(str(self.run.run_uid))  # type: ignore[attr-defined]


@strawberry_django.type(RunEvent)
class RunEventType(relay.Node):
    sequence_no: int
    event_type: str
    payload: strawberry.scalars.JSON
    created_at: datetime
    callback_event_id: uuid.UUID | None
    batch_id: uuid.UUID | None


@strawberry_django.type(Conversation)
class ConversationType(relay.Node):
    conversation_uid: uuid.UUID
    title: str
    created_at: datetime

    runs: DjangoListConnection[RunType] = strawberry_django.connection()

    @strawberry_django.field(select_related=["agent"])
    def agent_name(self) -> str:
        return str(cast("Conversation", self).agent.name)

    @strawberry_django.field
    def agent_id(self) -> strawberry.ID:
        return strawberry.ID(
            relay.to_base64("AgentType", cast("Conversation", self).agent_id),
        )

    @strawberry_django.field(select_related=["end_user"])
    def end_user_external_id(self) -> str | None:
        eu = cast("Conversation", self).end_user
        return str(eu.external_user_id) if eu else None


@strawberry_django.type(Run)
class RunType(relay.Node):
    run_uid: uuid.UUID
    status: RunStatusEnum
    summary: str
    error_message: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    total_tokens: int
    total_cost_currency: str
    is_scheduled: bool
    manifest_id: uuid.UUID | None
    last_callback_at: datetime | None

    events: DjangoListConnection[RunEventType] = strawberry_django.connection()

    @strawberry_django.field(select_related=["rating"])
    def rating(self) -> RatingType | None:
        try:
            return cast("RatingType", cast("Run", self).rating)
        except ObjectDoesNotExist:
            return None

    @strawberry_django.field
    def prompt_preview(self) -> str:
        text: str = self.prompt  # type: ignore[attr-defined]
        limit = 200
        return text[:limit]

    @strawberry_django.field
    def total_cost(self) -> Decimal:
        return Decimal(self.total_cost_usd)  # type: ignore[attr-defined]

    @strawberry_django.field(select_related=["agent"])
    def agent_name(self) -> str:
        return str(self.agent.name)  # type: ignore[attr-defined]

    @strawberry_django.field
    def agent_id(self) -> strawberry.ID:
        return strawberry.ID(relay.to_base64("AgentType", self.agent_id))

    @strawberry_django.field(select_related=["end_user"])
    def end_user_id_external(self) -> str:
        return str(self.end_user.external_user_id)  # type: ignore[attr-defined]

    @strawberry_django.field(select_related=["conversation"])
    def conversation(self) -> ConversationType | None:
        conv = cast("Run", self).conversation
        return cast("ConversationType", conv) if conv else None

    @strawberry_django.field
    def sandbox_url(self) -> str | None:
        run = cast("Run", self)
        if run.status != RunStatus.RUNNING or not run.sandbox_id:
            return None
        from config.runtime import runtime  # noqa: PLC0415

        return f"https://{run.sandbox_id}.{runtime.sandbox_domain}"


@strawberry.type
class ScoreBucket:
    score: int
    count: int


@strawberry.type
class RatingStats:
    average: float | None
    total_count: int
    distribution: list[ScoreBucket]


@strawberry.type
class SubmitRatingPayload(MutationResult):
    rating: RatingType | None = None


@strawberry.type
class StartRunPayload(MutationResult):
    run_id: strawberry.ID | None = None
    run_uid: uuid.UUID | None = None
    sandbox_url: str | None = None
    capability_token: str | None = None
    token_expires_at: datetime | None = None


@strawberry.type
class WakeForRunPayload(MutationResult):
    sandbox_url: str | None = None
    capability_token: str | None = None
    token_expires_at: datetime | None = None


@strawberry.type
class RefreshTokenPayload(MutationResult):
    capability_token: str | None = None
    token_expires_at: datetime | None = None
