"""RunState — projected current state of a run.

Composed by `apps.runs.Run.record_event` (Phase 2) from the append-only
stream of `UsageEvent`s. Read by the dashboard's `/runs/[id]` page and the
SDK so they don't have to re-derive state from raw events.

`LeaseUsage` mirrors the runtime usage totals contract field-for-field.
The metering receiver projects each `RunUsage` into the latest `LeaseUsage`
on `RunState`; the cumulative shape means we never need to replay history
to answer "how much has this run used so far".
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.runs.schemas.errors import DomainErrorCode, LeaseErrorCode
from apps.runs.schemas.events import (
    RunStatus,
)
from apps.runs.schemas.lease import LeaseUsage


class RunState(BaseModel):
    """Snapshot of a run at a point in time. Built by `Run.record_event`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    status: RunStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    lease_used: LeaseUsage = Field(default_factory=LeaseUsage)
    last_event_at: datetime | None = None
    summary: str = Field(default="", max_length=4_000)
    error_code: LeaseErrorCode | DomainErrorCode | None = None
