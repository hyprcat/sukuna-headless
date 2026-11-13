from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.workspaces.factories import (
    InvitationFactory,
    UserFactory,
    WorkspaceFactory,
)
from apps.workspaces.models import Workspace
from apps.workspaces.models.member import WorkspaceMember, WorkspaceRole

from .conftest import schema, session_ctx, verified_user

pytestmark = pytest.mark.django_db


# --- createWorkspace ---


CREATE_WORKSPACE = """
mutation($input: CreateWorkspaceInput!) {
    createWorkspace(input: $input) {
        success
        errors { code message field }
        workspace { name slug }
    }
}
"""


def test_create_workspace_happy_path() -> None:
    user = verified_user()
    ctx = session_ctx(user)
    result = schema.execute_sync(
        CREATE_WORKSPACE,
        variable_values={"input": {"name": "My Workspace"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["createWorkspace"]
    assert data["success"] is True
    assert data["workspace"]["name"] == "My Workspace"
    assert data["workspace"]["slug"] == "my-workspace"
    ws = Workspace.objects.get(slug="my-workspace")
    assert ws.owner == user
    assert ws.members.filter(user=user, role=WorkspaceRole.ADMIN).exists()


def test_create_workspace_custom_slug() -> None:
    user = verified_user()
    ctx = session_ctx(user)
    result = schema.execute_sync(
        CREATE_WORKSPACE,
        variable_values={"input": {"name": "My Workspace", "slug": "custom-slug"}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["createWorkspace"]["workspace"]["slug"] == "custom-slug"


def test_create_workspace_duplicate_slug() -> None:
    WorkspaceFactory(slug="taken")
    user = verified_user()
    ctx = session_ctx(user)
    result = schema.execute_sync(
        CREATE_WORKSPACE,
        variable_values={"input": {"name": "X", "slug": "taken"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["createWorkspace"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


def test_create_workspace_unverified_email() -> None:
    user = UserFactory()
    ctx = session_ctx(user)
    result = schema.execute_sync(
        CREATE_WORKSPACE,
        variable_values={"input": {"name": "Nope"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["createWorkspace"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "PERMISSION_DENIED"


def test_create_workspace_blank_name() -> None:
    user = verified_user()
    ctx = session_ctx(user)
    result = schema.execute_sync(
        CREATE_WORKSPACE,
        variable_values={"input": {"name": "  "}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["createWorkspace"]
    assert data["success"] is False


# --- updateWorkspace ---


UPDATE_WORKSPACE = """
mutation($input: UpdateWorkspaceInput!) {
    updateWorkspace(input: $input) {
        success
        errors { code message field }
        workspace { name billingEmail }
    }
}
"""


def test_update_workspace_name() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        UPDATE_WORKSPACE,
        variable_values={"input": {"name": "Renamed"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["updateWorkspace"]
    assert data["success"] is True
    assert data["workspace"]["name"] == "Renamed"


def test_update_workspace_billing_email() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        UPDATE_WORKSPACE,
        variable_values={"input": {"billingEmail": "billing@example.com"}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["updateWorkspace"]["workspace"]["billingEmail"] == "billing@example.com"


def test_update_workspace_rejects_invalid_billing_email() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user, billing_email="old@example.com")
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        UPDATE_WORKSPACE,
        variable_values={"input": {"billingEmail": "not-an-email"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["updateWorkspace"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "billing_email"
    assert data["errors"][0]["message"] == "Enter a valid billing email."
    ws.refresh_from_db()
    assert ws.billing_email == "old@example.com"


# --- acceptWorkspaceInvitation ---


ACCEPT_INVITATION = """
mutation($input: AcceptWorkspaceInvitationInput!) {
    acceptWorkspaceInvitation(input: $input) {
        success
        errors { code message }
        member { role }
    }
}
"""


def test_accept_invitation_happy_path() -> None:
    ws = WorkspaceFactory()
    invitee = UserFactory(email="invited@example.com")
    inv = InvitationFactory(workspace=ws, email="invited@example.com", role=WorkspaceRole.EDITOR)
    ctx = session_ctx(invitee)
    result = schema.execute_sync(
        ACCEPT_INVITATION,
        variable_values={"input": {"token": inv.token}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["acceptWorkspaceInvitation"]
    assert data["success"] is True
    assert data["member"]["role"] == "editor"
    assert WorkspaceMember.objects.filter(workspace=ws, user=invitee).exists()


def test_accept_invitation_wrong_email() -> None:
    ws = WorkspaceFactory()
    wrong_user = UserFactory(email="wrong@example.com")
    inv = InvitationFactory(workspace=ws, email="right@example.com")
    ctx = session_ctx(wrong_user)
    result = schema.execute_sync(
        ACCEPT_INVITATION,
        variable_values={"input": {"token": inv.token}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["acceptWorkspaceInvitation"]
    assert data["success"] is False


def test_accept_invitation_bad_token() -> None:
    user = UserFactory()
    ctx = session_ctx(user)
    result = schema.execute_sync(
        ACCEPT_INVITATION,
        variable_values={"input": {"token": "bogus-token"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["acceptWorkspaceInvitation"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "NOT_FOUND"


def test_accept_invitation_rejects_expired_token() -> None:
    user = UserFactory(email="expired-accept@example.com")
    inv = InvitationFactory(
        email=user.email,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    ctx = session_ctx(user)
    result = schema.execute_sync(
        ACCEPT_INVITATION,
        variable_values={"input": {"token": inv.token}},
        context_value=ctx,
    )
    data = result.data["acceptWorkspaceInvitation"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


def test_accept_invitation_is_session_only() -> None:
    inv = InvitationFactory(email="anonymous@example.com")
    result = schema.execute_sync(
        ACCEPT_INVITATION,
        variable_values={"input": {"token": inv.token}},
        context_value=session_ctx(None),
    )
    data = result.data["acceptWorkspaceInvitation"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "PERMISSION_DENIED"


# --- pendingInvitations query ---


PENDING_INVITATIONS = """
query {
    pendingInvitations { email role pending }
}
"""


def test_pending_invitations_query() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    InvitationFactory(workspace=ws, email="a@b.com")
    InvitationFactory(workspace=ws, email="c@d.com")
    InvitationFactory(
        workspace=ws, email="expired@b.com", expires_at=timezone.now() - timedelta(hours=1)
    )
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(PENDING_INVITATIONS, context_value=ctx)
    assert result.errors is None
    invitations = result.data["pendingInvitations"]
    assert len(invitations) == 2
    emails = {i["email"] for i in invitations}
    assert "a@b.com" in emails
    assert "expired@b.com" not in emails
