"""Tagged-union principal types — what authenticates a request.

`SessionPrincipal` represents a logged-in dashboard user acting through a
specific workspace membership; `ApiKeyPrincipal` represents a headless caller
holding a workspace-scoped API key. The auth backend in
:mod:`apps.api_keys.auth` builds one or the other and attaches it to the
request; resolvers consume them via the decorators in
:mod:`apps.core.decorators` and :mod:`apps.api_keys.decorators`.

The shared surface (`workspace_id`, `member`, `scopes`) is what those
decorators rely on — keep both classes structurally compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.api_keys.models import APIKey
    from apps.workspaces.models import WorkspaceMember


@dataclass(frozen=True, slots=True)
class SessionPrincipal:
    """A dashboard user acting on a workspace they belong to."""

    user: User
    member: WorkspaceMember
    role: str

    @property
    def workspace_id(self) -> int:
        return self.member.workspace_id

    # Sessions never carry scopes — those live on API keys. Returning an empty
    # frozenset (rather than `None`) keeps the `Principal` surface uniform so
    # `@requires_scope` can fail-closed without a type narrowing dance.
    scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ApiKeyPrincipal:
    """A headless caller authenticated by a workspace-scoped API key."""

    api_key: APIKey
    scopes: frozenset[str]

    @property
    def workspace_id(self) -> int:
        return self.api_key.workspace_id

    # API keys never carry a workspace membership — they're not a person.
    # Decorators that need `member.can(...)` fail closed when this is `None`.
    member: None = None


Principal = SessionPrincipal | ApiKeyPrincipal
