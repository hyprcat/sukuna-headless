"""Resolver decorators — workspace scoping and per-action authorization.

Phase-5 GraphQL resolvers wrap their bodies with these so each call site
auths uniformly: `@workspace_scoped` rejects cross-workspace requests,
`@requires_role(action)` enforces the action surface from
`apps.accounts.permissions.ROLE_PERMISSIONS`. `@requires_scope(scope)` for
API-key principals lives in `apps.api_keys.decorators` (Phase 2 below).

The resolver context shape — `Workspace` + `Principal` (`SessionPrincipal` |
`ApiKeyPrincipal`) — solidifies in Phase 5; the protocols below are what
this module actually depends on so it ships before Phases 3 and 5 do.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, Protocol, runtime_checkable

from apps.core.exceptions import PermissionDenied, ScopeInsufficient


@runtime_checkable
class _PermissionCheck(Protocol):
    """Anything that knows whether an action is permitted (i.e. `WorkspaceMember`)."""

    def can(self, action: str) -> bool: ...


@runtime_checkable
class _Principal(Protocol):
    """Common surface across `SessionPrincipal` and `ApiKeyPrincipal`."""

    workspace_id: int
    member: _PermissionCheck | None  # populated for session principals only


@runtime_checkable
class _ScopedPrincipal(_Principal, Protocol):
    """Anything that carries a closed set of scopes — i.e. API-key principals."""

    scopes: frozenset[str]


def workspace_scoped[F: Callable[..., Any]](resolver: F) -> F:
    """Reject calls whose principal is not bound to the resolved workspace."""

    @wraps(resolver)
    def _wrapped(root: Any, info: Any, *args: Any, **kwargs: Any) -> Any:
        principal: _Principal | None = info.context.principal
        workspace = info.context.workspace
        if principal is None or workspace is None:
            raise PermissionDenied("Workspace context required.")
        if principal.workspace_id != workspace.pk:
            raise PermissionDenied("Workspace scope violation.")
        return resolver(root, info, *args, **kwargs)

    return _wrapped  # type: ignore[return-value]


def requires_role(action: str) -> Callable[..., Any]:
    """Reject calls whose session principal's role lacks `action`."""

    def decorator[F: Callable[..., Any]](resolver: F) -> F:
        return _decorate_role(resolver, action)

    return decorator


def _decorate_role[F: Callable[..., Any]](resolver: F, action: str) -> F:
    resolver._required_role_action = action  # type: ignore[attr-defined]

    @wraps(resolver)
    def _wrapped(root: Any, info: Any, *args: Any, **kwargs: Any) -> Any:
        principal: _Principal | None = info.context.principal
        _guard_role(principal, resolver, _wrapped, action)
        return resolver(root, info, *args, **kwargs)

    _wrapped._required_role_action = action  # type: ignore[attr-defined]
    return _wrapped  # type: ignore[return-value]


def _guard_role(
    principal: _Principal | None,
    resolver: Callable[..., Any],
    wrapped: Callable[..., Any],
    action: str,
) -> None:
    if principal is None:
        raise PermissionDenied("Session required for this operation.")
    member = principal.member
    if member is None and _has_scope_check(resolver, wrapped):
        return
    if member is None or not member.can(action):
        raise PermissionDenied(f"Action {action!r} not permitted.")


def requires_scope(scope: str) -> Callable[..., Any]:
    """Reject calls whose API-key principal lacks `scope`."""

    def decorator[F: Callable[..., Any]](resolver: F) -> F:
        return _decorate_scope(resolver, scope)

    return decorator


def _decorate_scope[F: Callable[..., Any]](resolver: F, scope: str) -> F:
    resolver._required_scope = scope  # type: ignore[attr-defined]

    @wraps(resolver)
    def _wrapped(root: Any, info: Any, *args: Any, **kwargs: Any) -> Any:
        principal: _ScopedPrincipal | None = info.context.principal
        _guard_scope(principal, resolver, _wrapped, scope)
        return resolver(root, info, *args, **kwargs)

    _wrapped._required_scope = scope  # type: ignore[attr-defined]
    return _wrapped  # type: ignore[return-value]


def _guard_scope(
    principal: _ScopedPrincipal | None,
    resolver: Callable[..., Any],
    wrapped: Callable[..., Any],
    scope: str,
) -> None:
    if principal is None:
        raise PermissionDenied("API key required for this operation.")
    if not principal.scopes and _has_role_check(resolver, wrapped):
        return
    if not principal.scopes:
        raise PermissionDenied("API key required for this operation.")
    if scope not in principal.scopes:
        raise ScopeInsufficient(f"Scope {scope!r} not granted to this API key.")


def _has_scope_check(*resolvers: Callable[..., Any]) -> bool:
    return any(hasattr(resolver, "_required_scope") for resolver in resolvers)


def _has_role_check(*resolvers: Callable[..., Any]) -> bool:
    return any(hasattr(resolver, "_required_role_action") for resolver in resolvers)
