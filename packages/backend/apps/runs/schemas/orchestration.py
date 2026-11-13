"""Frozen config and result types for run orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from datetime import datetime


class RunOrchestrationDefaults(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_runtime_seconds: int = 3600
    max_total_tokens: int = 1_000_000
    max_cost_usd: Decimal = Decimal("50.00")
    scopes: tuple[str, ...] = (
        "stream:read",
        "hitl:respond",
        "run:cancel",
        "files:rw",
        "mcp:manage",
    )


class DenialMessages(BaseModel):
    model_config = ConfigDict(frozen=True)

    insufficient_credits: str = "End user has insufficient credits."
    run_limit_exceeded: str = "End user run limit exceeded."
    concurrency_cap: str = "End user concurrency cap reached."
    tool_not_allowed: str = Field(
        default="Requested tool not allowed for this end user.",
    )
    knowledge_not_allowed: str = Field(
        default="Requested knowledge not allowed for this end user.",
    )
    billing_error: str = "Workspace has insufficient funds."
    permission_denied: str = Field(
        default="End user is not active or not in this workspace.",
    )
    fallback: str = "Run denied."


@dataclass(frozen=True, slots=True)
class StartRunResult:
    run_id: int
    run_uid: uuid.UUID
    sandbox_url: str
    capability_token: str
    token_expires_at: datetime


@dataclass(frozen=True, slots=True)
class WakeForRunResult:
    sandbox_url: str
    capability_token: str
    token_expires_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshTokenResult:
    capability_token: str
    token_expires_at: datetime
