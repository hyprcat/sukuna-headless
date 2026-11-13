"""Closed scope vocabulary an `APIKey` may carry.

Wire-stable: adding a scope here is a deliberate schema change. Use the
same `resource:verb` shape as `apps/accounts/permissions.py` action strings
so dual-mode resolvers can mix the two without translation.

Per BACKEND_CODING_STANDARDS §2: collections of related values are Pydantic
models, not bare frozensets. Instantiate `APIKeyScopes()` at the use site
or accept it as a DI parameter.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class APIKeyScopes(BaseModel):
    model_config = ConfigDict(frozen=True)

    values: frozenset[str] = frozenset(
        {
            "agents:read",
            "agents:write",
            "runs:write",
            "runs:read",
            "tools:read",
            "tools:write",
            "knowledge:read",
            "knowledge:write",
            "end_users:write",
            "end_users:read",
            "workspace:read",
        }
    )
