from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class OutputRouteKind(StrEnum):
    WEBHOOK = "webhook"
    EMAIL = "email"
    ARTIFACT = "artifact"
    INTERNAL = "internal"


class OutputRoute(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: OutputRouteKind
    destination: str = Field(max_length=2048)
