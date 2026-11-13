from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.cache import cache
from django.http import HttpResponse

from apps.api_keys.auth import WorkspacePrincipalMiddleware
from apps.api_keys.factories import create_with_secret
from apps.api_keys.models import APIKey
from apps.api_keys.principals import ApiKeyPrincipal, SessionPrincipal
from apps.workspaces.factories import (
    UserFactory,
    WorkspaceFactory,
    WorkspaceMemberFactory,
)

pytestmark = pytest.mark.django_db


def _request(headers: dict[str, str], *, user: Any = None) -> SimpleNamespace:
    """Minimal stand-in for HttpRequest — middleware only reads headers + user."""
    anon = SimpleNamespace(is_authenticated=False)
    return SimpleNamespace(
        headers=headers,
        user=user if user is not None else anon,
    )


@pytest.fixture(autouse=True)
def _clear_audit_cache() -> None:
    cache.clear()


def _build_middleware() -> WorkspacePrincipalMiddleware:
    return WorkspacePrincipalMiddleware(lambda _request: HttpResponse(status=200))


def test_valid_bearer_attaches_api_key_principal() -> None:
    api_key, secret = create_with_secret(scopes=("runs:read",))
    middleware = _build_middleware()
    request = _request({"Authorization": f"Bearer {secret}"})

    middleware(request)

    assert isinstance(request.principal, ApiKeyPrincipal)
    assert request.principal.api_key.pk == api_key.pk
    assert request.workspace.pk == api_key.workspace_id
    assert request.workspace_id == api_key.workspace_id


def test_invalid_bearer_leaves_principal_unset() -> None:
    middleware = _build_middleware()
    request = _request({"Authorization": "Bearer ms_dev_garbageprefix000"})

    middleware(request)

    assert request.principal is None
    assert request.workspace is None


def test_malformed_authorization_does_not_fall_back_to_session() -> None:
    workspace = WorkspaceFactory()
    user = UserFactory()
    WorkspaceMemberFactory(workspace=workspace, user=user)
    middleware = _build_middleware()
    request = _request(
        {"Authorization": "Bearer github_pat_aaaaaaaaaaaa", "X-Workspace-Slug": workspace.slug},
        user=user,
    )

    middleware(request)

    assert request.principal is None
    assert request.workspace is None


def test_prefix_collision_checks_later_candidate() -> None:
    target, secret = create_with_secret(scopes=("runs:read",))
    APIKey._create_row(
        workspace=target.workspace,
        name="collision",
        key_prefix=target.key_prefix,
        secret="not-the-presented-secret",
        scopes=["runs:read"],
        created_by=None,
        expires_at=None,
    )
    middleware = _build_middleware()
    request = _request({"Authorization": f"Bearer {secret}"})

    middleware(request)

    assert isinstance(request.principal, ApiKeyPrincipal)
    assert request.principal.api_key.pk == target.pk


def test_revoked_key_is_not_accepted() -> None:
    api_key, secret = create_with_secret(scopes=("runs:read",))
    api_key.revoke(reason="rotation")
    middleware = _build_middleware()
    request = _request({"Authorization": f"Bearer {secret}"})

    middleware(request)

    assert request.principal is None


def test_session_principal_built_from_workspace_slug_header() -> None:
    workspace = WorkspaceFactory()
    user = UserFactory()
    member = WorkspaceMemberFactory(workspace=workspace, user=user)

    middleware = _build_middleware()
    request = _request({"X-Workspace-Slug": workspace.slug}, user=user)
    middleware(request)

    assert isinstance(request.principal, SessionPrincipal)
    assert request.principal.member.pk == member.pk
    assert request.workspace.pk == workspace.pk


def test_session_without_workspace_slug_leaves_principal_unset() -> None:
    user = UserFactory()

    middleware = _build_middleware()
    request = _request({}, user=user)
    middleware(request)

    assert request.principal is None


def test_session_with_unknown_slug_leaves_principal_unset() -> None:
    user = UserFactory()

    middleware = _build_middleware()
    request = _request({"X-Workspace-Slug": "no-such-workspace"}, user=user)
    middleware(request)

    assert request.principal is None


def test_no_auth_header_or_session_leaves_principal_unset() -> None:
    middleware = _build_middleware()
    request = _request({})
    middleware(request)

    assert request.principal is None
    assert request.workspace is None
    assert request.workspace_id is None


def test_bearer_with_wrong_namespace_is_rejected() -> None:
    middleware = _build_middleware()
    request = _request({"Authorization": "Bearer github_pat_aaaaaaaaaaaa"})
    middleware(request)

    assert request.principal is None


def test_bearer_with_wrong_environment_is_rejected() -> None:
    # Test settings run with environment=test by default; a prod-prefixed key
    # for the same workspace must be ignored.
    middleware = _build_middleware()
    request = _request({"Authorization": "Bearer ms_prod_aaaaaaaa00000000"})
    middleware(request)

    assert request.principal is None
