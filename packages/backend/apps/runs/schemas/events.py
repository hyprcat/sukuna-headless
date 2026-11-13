"""UsageEvent — the lifecycle / metering payloads `agent_server` emits.

Discriminated by the wire-stable `type` field, matching what the sandbox's
`engine.run` actually sends:

  - ``run_started``    — emitted once when the harness is wired up
  - ``run_usage``      — periodic; carries running totals (input/output/total
                          tokens, cost, native + MCP tool-call counters)
  - ``run_completed``  — terminal success
  - ``run_failed``     — terminal failure; carries an ``error`` message and
                          optional ``error_code``
  - ``run_cancelled``  — terminal cancellation (caller-initiated)

The class is named `RunFinished` (per `context/todo.md`'s class list) but the
on-the-wire discriminator value is ``"run_completed"`` because that is the
runtime's current documented event name. Couple to the wire, not to the doc
spelling.

Per-event fields mirror the runtime's usage totals contract so the sandbox
payload deserializes without translation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.runs.schemas.errors import DomainErrorCode, LeaseErrorCode


class RunStatus(StrEnum):
    """Backend-side run state machine. Mirrors `apps.runs.Run.state`."""

    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class _BaseEvent(BaseModel):
    """Fields every event carries. Subclasses pin the `type` discriminator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    sequence_no: int = Field(ge=0, default=0)
    emitted_at: datetime | None = None


class RunStarted(_BaseEvent):
    type: Literal["run_started"] = "run_started"
    sandbox_id: str | None = None


class RunUsage(_BaseEvent):
    """Periodic running-totals snapshot.

    Mirrors the runtime usage totals contract field-for-field. Each
    emission is the *cumulative* state at that moment; the metering receiver
    derives per-tick deltas by subtracting the previous `RunUsage` for the
    same `run_id`.
    """

    type: Literal["run_usage"] = "run_usage"
    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    total_tokens: int = Field(ge=0, default=0)
    cost_usd: Decimal = Field(ge=Decimal("0"), default=Decimal("0"))
    native_tool_calls: int = Field(ge=0, default=0)
    mcp_tool_calls: int = Field(ge=0, default=0)


class RunFinished(_BaseEvent):
    """Terminal-success event.

    Wire discriminator is ``"run_completed"`` to match the sandbox emission;
    the Python class name follows `context/todo.md`. The `final_*` fields
    are the *cumulative* counters at completion — the receiver uses
    `final_cost_usd` for the wallet debit on the matching transaction.
    """

    type: Literal["run_completed"] = "run_completed"
    final_input_tokens: int = Field(ge=0, default=0)
    final_output_tokens: int = Field(ge=0, default=0)
    final_total_tokens: int = Field(ge=0, default=0)
    final_cost_usd: Decimal = Field(ge=Decimal("0"), default=Decimal("0"))


class RunFailed(_BaseEvent):
    """Terminal-failure event. `error_code` distinguishes lease vs. domain causes."""

    type: Literal["run_failed"] = "run_failed"
    error: str = Field(min_length=1)
    error_code: LeaseErrorCode | DomainErrorCode | None = None
    final_cost_usd: Decimal = Field(ge=Decimal("0"), default=Decimal("0"))


class RunCancelled(_BaseEvent):
    type: Literal["run_cancelled"] = "run_cancelled"
    final_cost_usd: Decimal = Field(ge=Decimal("0"), default=Decimal("0"))


UsageEvent = Annotated[
    RunStarted | RunUsage | RunFinished | RunFailed | RunCancelled,
    Field(discriminator="type"),
]
"""Tagged union — Pydantic picks the variant from the wire `type` field.

Use `pydantic.TypeAdapter(UsageEvent).validate_python(payload)` at the
metering-receiver boundary; never branch on `payload["type"]` by hand.
"""
