from __future__ import annotations

from types import SimpleNamespace

import pytest
import strawberry

from apps.accounts.api.queries import ViewerQuery
from apps.api_keys.factories import APIKeyFactory
from apps.api_keys.principals import ApiKeyPrincipal, SessionPrincipal
from apps.workspaces.factories import UserFactory, WorkspaceFactory, WorkspaceMemberFactory
from apps.workspaces.models.member import WorkspaceRole

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q(ViewerQuery):
    pass


_schema = strawberry.Schema(query=_Q)


def _anon_ctx() -> SimpleNamespace:
    user = SimpleNamespace(is_authenticated=False)
    return SimpleNamespace(request=SimpleNamespace(user=user, workspace=None, principal=None))


def _session_ctx(
    user: object,
    workspace: object = None,
    principal: object = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        request=SimpleNamespace(user=user, workspace=workspace, principal=principal),
    )


VIEWER_QUERY = """
query {
    viewer {
        user { id email fullName isEmailVerified }
        workspaces { id name slug role }
        currentWorkspace { name slug }
    }
}
"""


def test_viewer_unauthenticated_returns_null() -> None:
    result = _schema.execute_sync(VIEWER_QUERY, context_value=_anon_ctx())
    assert result.errors is None
    assert result.data["viewer"] is None


def test_viewer_returns_user_info() -> None:
    user = UserFactory(email="alice@test.com", full_name="Alice Smith")
    user.verify_email()
    WorkspaceFactory(owner=user)
    ctx = _session_ctx(user)
    result = _schema.execute_sync(VIEWER_QUERY, context_value=ctx)
    assert result.errors is None
    viewer = result.data["viewer"]
    assert viewer["user"]["email"] == "alice@test.com"
    assert viewer["user"]["fullName"] == "Alice Smith"
    assert viewer["user"]["isEmailVerified"] is True


def test_viewer_returns_workspaces_with_roles() -> None:
    user = UserFactory()
    WorkspaceFactory(name="Alpha", owner=user)
    ws2 = WorkspaceFactory(name="Beta")
    WorkspaceMemberFactory(workspace=ws2, user=user, role=WorkspaceRole.VIEWER)
    ctx = _session_ctx(user)
    result = _schema.execute_sync(VIEWER_QUERY, context_value=ctx)
    assert result.errors is None
    workspaces = result.data["viewer"]["workspaces"]
    assert len(workspaces) == 2
    assert workspaces[0]["name"] == "Alpha"
    assert workspaces[0]["role"] == "admin"
    assert workspaces[1]["name"] == "Beta"
    assert workspaces[1]["role"] == "viewer"


def test_viewer_returns_current_workspace_when_set() -> None:
    user = UserFactory()
    ws = WorkspaceFactory(name="Active WS", owner=user)
    member = ws.members.get(user=user)
    principal = SessionPrincipal(user=user, member=member, role=member.role)
    ctx = _session_ctx(user, workspace=ws, principal=principal)
    result = _schema.execute_sync(VIEWER_QUERY, context_value=ctx)
    assert result.errors is None
    current = result.data["viewer"]["currentWorkspace"]
    assert current is not None
    assert current["name"] == "Active WS"
    assert current["slug"] == ws.slug


def test_viewer_current_workspace_null_when_not_set() -> None:
    user = UserFactory()
    WorkspaceFactory(owner=user)
    ctx = _session_ctx(user, workspace=None)
    result = _schema.execute_sync(VIEWER_QUERY, context_value=ctx)
    assert result.errors is None
    assert result.data["viewer"]["currentWorkspace"] is None


def test_viewer_ignores_loose_workspace_without_session_principal() -> None:
    user = UserFactory()
    ws = WorkspaceFactory(owner=user)
    ctx = _session_ctx(user, workspace=ws)
    result = _schema.execute_sync(VIEWER_QUERY, context_value=ctx)
    assert result.errors is None
    assert result.data["viewer"]["currentWorkspace"] is None


def test_viewer_user_without_memberships() -> None:
    user = UserFactory()
    ctx = _session_ctx(user)
    result = _schema.execute_sync(VIEWER_QUERY, context_value=ctx)
    assert result.errors is None
    viewer = result.data["viewer"]
    assert viewer["workspaces"] == []
    assert viewer["currentWorkspace"] is None


def test_viewer_is_not_available_to_api_key_principal() -> None:
    user = UserFactory()
    api_workspace = WorkspaceFactory(name="API workspace")
    api_key = APIKeyFactory(workspace=api_workspace)
    principal = ApiKeyPrincipal(api_key=api_key, scopes=frozenset({"runs:read"}))
    ctx = _session_ctx(user, workspace=api_workspace, principal=principal)
    result = _schema.execute_sync(VIEWER_QUERY, context_value=ctx)
    assert result.errors is None
    assert result.data["viewer"] is None
