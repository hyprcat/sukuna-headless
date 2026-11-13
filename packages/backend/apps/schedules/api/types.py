from __future__ import annotations

from datetime import datetime
from enum import Enum

import strawberry
import strawberry_django
from django.db.models import Count
from strawberry import relay

from apps.core.api.types import MutationResult
from apps.schedules.models import Schedule, ScheduleExecution


@strawberry.enum
class ScheduleStatusEnum(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


@strawberry.enum
class FailureHandlingEnum(Enum):
    RETRY = "retry"
    SKIP = "skip"
    ALERT = "alert"
    LOG_SILENT = "log_silent"


@strawberry_django.type(Schedule)
class ScheduleType(relay.Node):
    name: str
    description: str
    prompt: str
    cron_expression: str
    failure_handling: FailureHandlingEnum
    output_routing: strawberry.scalars.JSON
    status: ScheduleStatusEnum
    next_run_at: datetime | None
    last_run_at: datetime | None
    consecutive_failures: int
    paused_at: datetime | None
    disabled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @strawberry_django.field(select_related=["agent"])
    def agent_name(self) -> str:
        return str(self.agent.name)  # type: ignore[attr-defined]

    @strawberry_django.field(select_related=["target_end_user"])
    def target_end_user_external_id(self) -> str:
        return str(self.target_end_user.external_user_id)  # type: ignore[attr-defined]

    executions_count: int = strawberry_django.field(annotate=Count("executions"))


@strawberry_django.type(ScheduleExecution)
class ScheduleExecutionType(relay.Node):
    outcome: str
    scheduled_for: datetime
    started_at: datetime | None
    finished_at: datetime | None
    skip_reason: str
    error_message: str
    created_at: datetime


@strawberry.type
class CreateSchedulePayload(MutationResult):
    schedule: ScheduleType | None = None


@strawberry.type
class UpdateSchedulePayload(MutationResult):
    schedule: ScheduleType | None = None


@strawberry.type
class PauseSchedulePayload(MutationResult):
    schedule: ScheduleType | None = None


@strawberry.type
class ResumeSchedulePayload(MutationResult):
    schedule: ScheduleType | None = None


@strawberry.type
class DisableSchedulePayload(MutationResult):
    schedule: ScheduleType | None = None
