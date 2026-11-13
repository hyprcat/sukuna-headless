from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from strawberry import relay

from apps.workspaces.factories import (
    UserFactory,
    WorkspaceFactory,
    WorkspaceMemberFactory,
)
from apps.workspaces.models.member import WorkspaceMember, WorkspaceRole

from .conftest import schema, session_ctx, verified_user

pytestmark = pytest.mark.django_db


# --- transferWorkspaceOwnership ---


TRANSFER_OWNERSHIP = """
mutation($input: TransferWorkspaceOwnershipInput!) {
    transferWorkspaceOwnership(input: $input) {
        success
        errors { code message field }
        workspace { ownerEmail ownerId }
    }
}
"""


def test_transfer_ownership_uses_input_contract() -> None:
    schema_sdl = str(schema)

    assert "transferWorkspaceOwnership(input: TransferWorkspaceOwnershipInput!" in schema_sdl
    assert "transferWorkspaceOwnership(userId:" not in schema_sdl


def test_transfer_ownership_happy_path() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    new_owner = UserFactory()
    WorkspaceMemberFactory(workspace=ws, user=new_owner, role=WorkspaceRole.ADMIN)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        TRANSFER_OWNERSHIP,
        variable_values={"input": {"userId": str(new_owner.pk)}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["transferWorkspaceOwnership"]
    assert data["success"] is True
    assert data["workspace"]["ownerEmail"] == new_owner.email
    assert data["workspace"]["ownerId"] == str(new_owner.pk)


def test_transfer_ownership_non_member() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    outsider = UserFactory()
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        TRANSFER_OWNERSHIP,
        variable_values={"input": {"userId": str(outsider.pk)}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["transferWorkspaceOwnership"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "user_id"


def test_transfer_ownership_accepts_viewer_user_global_id() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    new_owner = UserFactory()
    WorkspaceMemberFactory(workspace=ws, user=new_owner, role=WorkspaceRole.ADMIN)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        TRANSFER_OWNERSHIP,
        variable_values={"input": {"userId": relay.to_base64("ViewerUserType", new_owner.pk)}},
        context_value=ctx,
    )
    data = result.data["transferWorkspaceOwnership"]
    assert result.errors is None
    assert data["success"] is True
    assert data["workspace"]["ownerId"] == str(new_owner.pk)


def test_transfer_ownership_rejects_wrong_global_id_type() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.ADMIN)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        TRANSFER_OWNERSHIP,
        variable_values={"input": {"userId": relay.to_base64("WorkspaceMemberType", member.pk)}},
        context_value=ctx,
    )
    data = result.data["transferWorkspaceOwnership"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "user_id"


def test_transfer_ownership_permission_error_uses_payload() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    new_owner = UserFactory()
    WorkspaceMemberFactory(workspace=ws, user=new_owner, role=WorkspaceRole.ADMIN)
    ctx = session_ctx(user, ws, can_act=False)
    result = schema.execute_sync(
        TRANSFER_OWNERSHIP,
        variable_values={"input": {"userId": str(new_owner.pk)}},
        context_value=ctx,
    )
    data = result.data["transferWorkspaceOwnership"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "PERMISSION_DENIED"


# --- removeWorkspaceMember ---


REMOVE_MEMBER = """
mutation($memberId: ID!) {
    removeWorkspaceMember(memberId: $memberId) {
        success
        errors { code message }
    }
}
"""


def test_remove_member_happy_path() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.VIEWER)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        REMOVE_MEMBER,
        variable_values={"memberId": str(member.pk)},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["removeWorkspaceMember"]["success"] is True
    assert not WorkspaceMember.objects.filter(pk=member.pk).exists()


def test_remove_owner_fails() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    owner_member = ws.members.get(user=user)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        REMOVE_MEMBER,
        variable_values={"memberId": str(owner_member.pk)},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["removeWorkspaceMember"]["success"] is False


# --- updateWorkspaceMemberRole ---


UPDATE_ROLE = """
mutation($input: UpdateMemberRoleInput!) {
    updateWorkspaceMemberRole(input: $input) {
        success
        errors { code message }
        member { role }
    }
}
"""


def test_update_member_role() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.VIEWER)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        UPDATE_ROLE,
        variable_values={"input": {"memberId": str(member.pk), "role": "editor"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["updateWorkspaceMemberRole"]
    assert data["success"] is True
    assert data["member"]["role"] == "editor"


def test_update_member_role_invalid() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.VIEWER)
    ctx = session_ctx(user, ws)
    result = schema.execute_sync(
        UPDATE_ROLE,
        variable_values={"input": {"memberId": str(member.pk), "role": "superadmin"}},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["updateWorkspaceMemberRole"]["success"] is False


# --- workspaceMembers query ---


WORKSPACE_MEMBERS = """
query {
    workspaceMembers { userEmail userLastActiveAt }
}
"""


def test_workspace_members_exposes_user_last_active_at() -> None:
    user = verified_user()
    ws = WorkspaceFactory(owner=user)
    active_at = timezone.now() - timedelta(hours=2)
    active_user = UserFactory(email="active@example.com", last_login=active_at)
    WorkspaceMemberFactory(workspace=ws, user=active_user, role=WorkspaceRole.VIEWER)
    ctx = session_ctx(user, ws)

    result = schema.execute_sync(WORKSPACE_MEMBERS, context_value=ctx)

    assert result.errors is None
    member = next(
        item for item in result.data["workspaceMembers"] if item["userEmail"] == active_user.email
    )
    assert member["userLastActiveAt"] is not None
