"""Lease — the resource limits a single run is permitted to consume.

The backend computes a `Lease` from per-user controls (`context/business-rules.md`)
and hands it to `agent_server` at run start. The sandbox's `LeaseEnforcer`
checks runtime on every agent event and usage on every metering event; on
breach it emits a `RunFailed` carrying a `LeaseErrorCode`.

Validators enforce positive values plus sane upper bounds — the upper bounds
guard against runaway configuration, not against legitimate caps. Real caps
live on the `EndUser.ControlProfile`.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Lease(BaseModel):
    """Resource ceiling for one run. Crossed → `RunFailed(lease_*_exceeded)`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Upper bounds are runaway guards — anything past these is a config bug,
    # not a legitimate request. Real caps live on `EndUser.ControlProfile`.
    max_runtime_seconds: int = Field(gt=0, le=86_400)  # ≤ 1 day
    max_total_tokens: int = Field(gt=0, le=10_000_000)  # ≤ 10M tokens
    max_cost_usd: Decimal = Field(gt=Decimal("0"), le=Decimal("1000.00"))


class LeaseUsage(BaseModel):
    """Cumulative usage counters for a run. Mirrors the sandbox `UsageTotals`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = Field(ge=0, default=0)
    output_tokens: int = Field(ge=0, default=0)
    total_tokens: int = Field(ge=0, default=0)
    cost_usd: Decimal = Field(ge=Decimal("0"), default=Decimal("0"))
    native_tool_calls: int = Field(ge=0, default=0)
    mcp_tool_calls: int = Field(ge=0, default=0)
