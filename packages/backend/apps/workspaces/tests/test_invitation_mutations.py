from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone
from strawberry import relay

from apps.workspaces.factories import (
    InvitationFactory,
    WorkspaceFactory,
)
from apps.workspaces.models import Invitation

from .conftest import schema, session_ctx, verified_user

pytestmark = pytest.mark.django_db


# --- inviteWorkspaceMember ---


INVITE_MEMBER = """
mutation($input: InviteMemberInput!) {
    inviteWorkspaceMember(input: $input) {
        success
        errors { code message }
        invitation { email role pending }
    }
}
"""


@patch("apps.workspaces.api.mutations.send_invitation_email")
def test_invite_member_happy_path(mock_task: object) -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        INVITE_MEMBER,
        variable_values={"input": {"email": "new@example.com", "role": "editor"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["inviteWorkspaceMember"]
    assert data["success"] is True
    assert data["invitation"]["email"] == "new@example.com"
    assert data["invitation"]["role"] == "editor"
    assert data["invitation"]["pending"] is True
    assert Invitation.objects.filter(workspace=ws, email="new@example.com").exists()


@patch("apps.workspaces.api.mutations.send_invitation_email")
def test_invite_member_duplicate_pending(mock_task: object) -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    InvitationFactory(workspace=ws, email="dup@example.com")
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        INVITE_MEMBER,
        variable_values={"input": {"email": "dup@example.com"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["inviteWorkspaceMember"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


@patch("apps.workspaces.api.mutations.send_invitation_email")
def test_invite_member_invalid_role(mock_task: object) -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        INVITE_MEMBER,
        variable_values={"input": {"email": "a@b.com", "role": "superadmin"}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["inviteWorkspaceMember"]["success"] is False


# --- resendWorkspaceInvitation ---


RESEND_INVITATION = """
mutation($input: ResendWorkspaceInvitationInput!) {
    resendWorkspaceInvitation(input: $input) {
        success
        errors { code message field }
        invitation { email }
    }
}
"""


@patch("apps.workspaces.api.mutations.send_invitation_email")
def test_resend_invitation(mock_task: Mock) -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    inv = InvitationFactory(workspace=ws)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        RESEND_INVITATION,
        variable_values={"input": {"invitationId": str(inv.pk)}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["resendWorkspaceInvitation"]["success"] is True
    mock_task.enqueue.assert_called_once_with(inv.pk)


@patch("apps.workspaces.api.mutations.send_invitation_email")
def test_resend_invitation_accepts_relay_global_id(mock_task: Mock) -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    inv = InvitationFactory(workspace=ws)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        RESEND_INVITATION,
        variable_values={"input": {"invitationId": relay.to_base64("InvitationType", inv.pk)}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["resendWorkspaceInvitation"]["success"] is True
    mock_task.enqueue.assert_called_once_with(inv.pk)


@patch("apps.workspaces.api.mutations.send_invitation_email")
def test_resend_invitation_rejects_wrong_relay_id_type(mock_task: Mock) -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        RESEND_INVITATION,
        variable_values={"input": {"invitationId": relay.to_base64("WorkspaceType", ws.pk)}},
        context_value=ctx,
    )
    data = result.data["resendWorkspaceInvitation"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "invitation_id"
    mock_task.enqueue.assert_not_called()


@patch("apps.workspaces.api.mutations.send_invitation_email")
def test_resend_expired_invitation(mock_task: Mock) -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    inv = InvitationFactory(workspace=ws, expires_at=timezone.now() - timedelta(days=1))
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        RESEND_INVITATION,
        variable_values={"input": {"invitationId": str(inv.pk)}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["resendWorkspaceInvitation"]["success"] is False
    mock_task.enqueue.assert_not_called()


# --- revokeWorkspaceInvitation ---


REVOKE_INVITATION = """
mutation($input: RevokeWorkspaceInvitationInput!) {
    revokeWorkspaceInvitation(input: $input) {
        success
        errors { code message field }
    }
}
"""


@patch("apps.workspaces.api.mutations.send_invitation_email")
def test_revoke_invitation(mock_task: object) -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    inv = InvitationFactory(workspace=ws)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        REVOKE_INVITATION,
        variable_values={"input": {"invitationId": str(inv.pk)}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["revokeWorkspaceInvitation"]["success"] is True
    assert not Invitation.objects.filter(pk=inv.pk).exists()


def test_revoke_invitation_accepts_relay_global_id() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    inv = InvitationFactory(workspace=ws)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        REVOKE_INVITATION,
        variable_values={"input": {"invitationId": relay.to_base64("InvitationType", inv.pk)}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["revokeWorkspaceInvitation"]["success"] is True
    assert not Invitation.objects.filter(pk=inv.pk).exists()


def test_revoke_invitation_rejects_wrong_relay_id_type() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        REVOKE_INVITATION,
        variable_values={"input": {"invitationId": relay.to_base64("WorkspaceType", ws.pk)}},
        context_value=ctx,
    )
    data = result.data["revokeWorkspaceInvitation"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "invitation_id"


def test_revoke_nonexistent_invitation() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        REVOKE_INVITATION,
        variable_values={"input": {"invitationId": "99999"}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["revokeWorkspaceInvitation"]["success"] is False
    assert result.data["revokeWorkspaceInvitation"]["errors"][0]["code"] == "NOT_FOUND"
