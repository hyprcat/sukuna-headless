from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    email: str
    full_name: str
    email_verified: bool


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    name: str


class WorkspaceMembershipResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    role: str
