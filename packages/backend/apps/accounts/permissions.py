"""Role → action permissions matrix for workspace members.

Per BACKEND_CODING_STANDARDS §2 — no module-level constants. The action
vocabulary is the `Action` `StrEnum` below (a class definition); the
role-to-action matrix is the `RolePermissions` Pydantic model. Resolvers
reference `Action.AGENTS_WRITE`, never raw strings.

Kept in lockstep with `context/user-roles.md`:
  - Admin   — full access; workspace settings, billing, members, all CRUD.
  - Editor  — edits tools/knowledge/end-users/runs/schedules; cannot change
              billing or members; cannot delete agents.
  - Viewer  — read-only across the workspace.
"""

from __future__ import annotations

from enum import StrEnum
from typing import cast

from pydantic import BaseModel, ConfigDict, Field


class Action(StrEnum):
    """Closed vocabulary of permission action strings.

    Wire-stable: values appear in audit logs, API-key scopes (where they
    overlap), and any persisted permission grant. Renaming a member is a
    breaking change. Use the same `resource:verb` shape as
    `apps.api_keys.scopes.APIKeyScopes` so dual-mode resolvers can mix the
    two without translation.
    """

    WORKSPACE_READ = "workspace:read"
    WORKSPACE_WRITE = "workspace:write"
    WORKSPACE_DELETE = "workspace:delete"
    WORKSPACE_SUSPEND = "workspace:suspend"

    MEMBERS_READ = "members:read"
    MEMBERS_INVITE = "members:invite"
    MEMBERS_UPDATE_ROLE = "members:update_role"
    MEMBERS_REMOVE = "members:remove"
    MEMBERS_TRANSFER_OWNERSHIP = "members:transfer_ownership"

    BILLING_READ = "billing:read"
    BILLING_TOPUP = "billing:topup"
    BILLING_REFUND = "billing:refund"

    API_KEYS_READ = "api_keys:read"
    API_KEYS_CREATE = "api_keys:create"
    API_KEYS_REVOKE = "api_keys:revoke"

    AGENTS_READ = "agents:read"
    AGENTS_WRITE = "agents:write"
    AGENTS_DELETE = "agents:delete"

    TOOLS_READ = "tools:read"
    TOOLS_WRITE = "tools:write"
    TOOLS_DELETE = "tools:delete"

    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"
    KNOWLEDGE_DELETE = "knowledge:delete"

    END_USERS_READ = "end_users:read"
    END_USERS_WRITE = "end_users:write"
    END_USERS_DELETE = "end_users:delete"

    RUNS_READ = "runs:read"
    RUNS_WRITE = "runs:write"
    RUNS_CANCEL = "runs:cancel"

    SCHEDULES_READ = "schedules:read"
    SCHEDULES_WRITE = "schedules:write"
    SCHEDULES_DELETE = "schedules:delete"
    SCHEDULES_PAUSE = "schedules:pause"

    POLICIES_READ = "policies:read"
    POLICIES_WRITE = "policies:write"

    RATINGS_READ = "ratings:read"

    INSIGHTS_READ = "insights:read"
    INSIGHTS_DISMISS = "insights:dismiss"
    INSIGHTS_PIN = "insights:pin"


def _viewer_actions() -> frozenset[Action]:
    return frozenset(
        {
            Action.WORKSPACE_READ,
            Action.MEMBERS_READ,
            Action.BILLING_READ,
            Action.API_KEYS_READ,
            Action.AGENTS_READ,
            Action.TOOLS_READ,
            Action.KNOWLEDGE_READ,
            Action.END_USERS_READ,
            Action.RUNS_READ,
            Action.SCHEDULES_READ,
            Action.POLICIES_READ,
            Action.RATINGS_READ,
            Action.INSIGHTS_READ,
        }
    )


def _editor_actions() -> frozenset[Action]:
    return _viewer_actions() | frozenset(
        {
            Action.AGENTS_WRITE,
            Action.TOOLS_WRITE,
            Action.TOOLS_DELETE,
            Action.KNOWLEDGE_WRITE,
            Action.KNOWLEDGE_DELETE,
            Action.END_USERS_WRITE,
            Action.END_USERS_DELETE,
            Action.RUNS_WRITE,
            Action.RUNS_CANCEL,
            Action.SCHEDULES_WRITE,
            Action.SCHEDULES_DELETE,
            Action.SCHEDULES_PAUSE,
            Action.POLICIES_WRITE,
            Action.INSIGHTS_DISMISS,
            Action.INSIGHTS_PIN,
        }
    )


class RolePermissions(BaseModel):
    """Per-role action allow-list. Frozen — callers cannot mutate the matrix.

    Membership-check via `for_role(role)`; resolver decorators in
    `apps.core.decorators` use this to gate session-authenticated calls.
    """

    model_config = ConfigDict(frozen=True)

    admin: frozenset[Action] = Field(default_factory=lambda: frozenset(Action))
    editor: frozenset[Action] = Field(default_factory=_editor_actions)
    viewer: frozenset[Action] = Field(default_factory=_viewer_actions)

    def for_role(self, role: str) -> frozenset[Action]:
        return cast("frozenset[Action]", getattr(self, role))
