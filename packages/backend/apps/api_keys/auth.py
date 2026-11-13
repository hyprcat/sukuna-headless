"""Workspace + principal resolver — Django middleware.

Builds an `ApiKeyPrincipal` from a `Authorization: Bearer ms_<env>_...`
header. When no `Authorization` header is present, it falls back to a
`SessionPrincipal` if Django session auth has populated `request.user` and
the caller has named a workspace via the `X-Workspace-Slug` header. Either
way it attaches `request.principal` and `request.workspace`; resolvers
consume both via the decorators in `apps.core.decorators` and
`apps.api_keys.decorators`.

Failed API-key lookups are audited via `record_event` with a per-prefix,
per-bucket rate limit so a brute-force probe doesn't drown the analytics
sink. The cache is the authoritative dedup — `cache.add` is the atomic
"first writer wins" primitive we need.

Format and rate-limit constants live on `APIKeyFormat` and
`AuthMiddlewareConfig` (frozen Pydantic models) per BACKEND_CODING_STANDARDS
§2 — no module-level globals; group related values into a `BaseModel`.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from django.core.cache import cache

from apps.accounts.models import User
from apps.api_keys.models import APIKey
from apps.api_keys.principals import ApiKeyPrincipal, SessionPrincipal
from apps.api_keys.schemas.config import APIKeyFormat, AuthMiddlewareConfig
from apps.core.events import record_event
from apps.workspaces.models import WorkspaceMember
from config.runtime import runtime

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse


class WorkspacePrincipalMiddleware:
    """Attach `request.principal` + `request.workspace` from the auth context."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.config = AuthMiddlewareConfig()
        self.format = APIKeyFormat()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.principal = None  # type: ignore[attr-defined]
        request.workspace = None  # type: ignore[attr-defined]
        request.workspace_id = None  # type: ignore[attr-defined]
        self._resolve(request)
        return self.get_response(request)

    def _resolve(self, request: HttpRequest) -> None:
        authorization = request.headers.get("Authorization")
        if authorization:
            bearer = self._extract_bearer(authorization)
            if bearer is not None:
                self._resolve_api_key(request, bearer)
            else:
                self._audit_failure("invalid_format", prefix=None)
            return
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            self._resolve_session(request)

    def _extract_bearer(self, authorization: str) -> str | None:
        if not authorization.startswith(self.config.bearer_prefix):
            return None
        bearer = authorization[len(self.config.bearer_prefix) :].strip()
        return bearer or None

    def _resolve_api_key(self, request: HttpRequest, bearer: str) -> None:
        prefix = self._parse_prefix(bearer)
        if prefix is None:
            self._audit_failure("invalid_format", prefix=None)
            return
        candidates = APIKey.objects.lookup_by_prefix(prefix).select_related("workspace")
        for candidate in candidates:
            if candidate.verify(bearer):
                self._attach_api_key(request, candidate)
                return
        self._audit_failure("not_found", prefix=prefix)

    @staticmethod
    def _attach_api_key(request: HttpRequest, candidate: APIKey) -> None:
        request.principal = ApiKeyPrincipal(  # type: ignore[attr-defined]
            api_key=candidate,
            scopes=frozenset(candidate.scopes),
        )
        request.workspace = candidate.workspace  # type: ignore[attr-defined]
        request.workspace_id = candidate.workspace_id  # type: ignore[attr-defined]
        candidate.record_use()

    def _parse_prefix(self, bearer: str) -> str | None:
        try:
            namespace, env, rest = bearer.split("_", 2)
        except ValueError:
            return None
        if namespace != self.format.namespace or env != runtime.environment:
            return None
        if len(rest) < self.format.prefix_length:
            return None
        return rest[: self.format.prefix_length]

    def _audit_failure(self, reason: str, *, prefix: str | None) -> None:
        bucket = int(time.time() // self.config.audit_bucket_seconds)
        cache_key = f"{self.config.audit_cache_key_prefix}:{prefix or 'na'}:{bucket}"
        if not cache.add(cache_key, 1, timeout=self.config.audit_ttl_seconds):
            return
        record_event(
            "api_key_lookup_failed",
            distinct_id=prefix or "anonymous",
            properties={"reason": reason, "prefix": prefix},
        )

    def _resolve_session(self, request: HttpRequest) -> None:
        slug = request.headers.get(self.config.workspace_slug_header)
        if not slug:
            return
        user = self._session_user(request)
        if user is None:
            return
        member = self._session_member(user, slug)
        if member is not None:
            self._attach_session(request, user, member)

    @staticmethod
    def _session_user(request: HttpRequest) -> User | None:
        user = request.user
        if not isinstance(user, User):
            return None
        return user

    @staticmethod
    def _session_member(user: User, slug: str) -> WorkspaceMember | None:
        return (
            WorkspaceMember.objects.select_related("workspace", "user")
            .filter(user=user, workspace__slug=slug)
            .first()
        )

    @staticmethod
    def _attach_session(request: HttpRequest, user: User, member: WorkspaceMember) -> None:
        request.principal = SessionPrincipal(  # type: ignore[attr-defined]
            user=user,
            member=member,
            role=member.role,
        )
        request.workspace = member.workspace  # type: ignore[attr-defined]
        request.workspace_id = member.workspace_id  # type: ignore[attr-defined]
