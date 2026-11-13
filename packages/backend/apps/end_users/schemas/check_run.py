"""Pure return types for the end-user run gate."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.core.errors import UserError


class Allowed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["allowed"] = "allowed"
    model_tier: str = Field(min_length=1)


class Denied(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["denied"] = "denied"
    reason: UserError
