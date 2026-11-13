from __future__ import annotations

from typing import cast

import strawberry
from django.db import IntegrityError
from strawberry.types import Info

from apps.accounts.models import User
from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, workspace_scoped
from apps.core.exceptions import Conflict, PermissionDenied
from apps.workspaces.api.types import (
    AcceptInvitationPayload,
    CreateWorkspacePayload,
    InvitationType,
    InviteMemberPayload,
    RemoveMemberPayload,
    RevokeInvitationPayload,
    TransferOwnershipPayload,
    UpdateMemberRolePayload,
    UpdateWorkspacePayload,
    WorkspaceMemberType,
    WorkspaceType,
)
from apps.workspaces.models import Invitation, Workspace
from apps.workspaces.tasks.emails import send_invitation_email


def _authenticated_user(info: Info) -> User:
    user = getattr(info.context.request, "user", None)
    if user is None or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    if not isinstance(user, User):
        raise PermissionDenied("Authentication required.")
    return user


def _get_invitation(workspace_pk: int, invitation_id: strawberry.ID) -> Invitation:
    pk = parse_int_id(invitation_id, expected_type="InvitationType", field="invitation_id")
    return Invitation.get_pending_or_raise(workspace_pk, pk)


@strawberry.input
class CreateWorkspaceInput:
    name: str
    slug: str = ""
    billing_email: str = ""


@strawberry.input
class UpdateWorkspaceInput:
    name: str | None = None
    billing_email: str | None = None


@strawberry.input
class InviteMemberInput:
    email: str
    role: str = "viewer"


@strawberry.input
class ResendWorkspaceInvitationInput:
    invitation_id: strawberry.ID


@strawberry.input
class RevokeWorkspaceInvitationInput:
    invitation_id: strawberry.ID


@strawberry.input
class AcceptWorkspaceInvitationInput:
    token: str


@strawberry.input
class TransferWorkspaceOwnershipInput:
    user_id: strawberry.ID


@strawberry.input
class UpdateMemberRoleInput:
    member_id: strawberry.ID
    role: str


@strawberry.type
class WorkspaceMutation:
    @strawberry.mutation
    @catch_domain_errors(CreateWorkspacePayload)
    def create_workspace(self, info: Info, input: CreateWorkspaceInput) -> CreateWorkspacePayload:
        user = _authenticated_user(info)
        if not user.is_email_verified:
            raise PermissionDenied("Verify your email before creating a workspace.")
        try:
            workspace = Workspace.create_for_user(
                user=user,
                name=input.name,
                slug=input.slug,
                billing_email=input.billing_email,
            )
        except IntegrityError:
            raise Conflict("A workspace with this slug already exists.", field="slug") from None
        return CreateWorkspacePayload(
            success=True, errors=[], workspace=cast("WorkspaceType", workspace)
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.WORKSPACE_WRITE)
    @catch_domain_errors(UpdateWorkspacePayload)
    def update_workspace(self, info: Info, input: UpdateWorkspaceInput) -> UpdateWorkspacePayload:
        workspace = info.context.workspace
        workspace.update_settings(name=input.name, billing_email=input.billing_email)
        workspace.refresh_from_db()
        return UpdateWorkspacePayload(
            success=True, errors=[], workspace=cast("WorkspaceType", workspace)
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.MEMBERS_INVITE)
    @catch_domain_errors(InviteMemberPayload)
    def invite_workspace_member(self, info: Info, input: InviteMemberInput) -> InviteMemberPayload:
        invitation = Invitation.create_for_workspace(
            workspace=info.context.workspace,
            email=input.email,
            role=input.role,
        )
        send_invitation_email.enqueue(invitation.pk)
        return InviteMemberPayload(
            success=True, errors=[], invitation=cast("InvitationType", invitation)
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.MEMBERS_INVITE)
    @catch_domain_errors(InviteMemberPayload)
    def resend_workspace_invitation(
        self, info: Info, input: ResendWorkspaceInvitationInput
    ) -> InviteMemberPayload:
        invitation = _get_invitation(info.context.workspace.pk, input.invitation_id)
        send_invitation_email.enqueue(invitation.pk)
        return InviteMemberPayload(
            success=True, errors=[], invitation=cast("InvitationType", invitation)
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.MEMBERS_INVITE)
    @catch_domain_errors(RevokeInvitationPayload)
    def revoke_workspace_invitation(
        self, info: Info, input: RevokeWorkspaceInvitationInput
    ) -> RevokeInvitationPayload:
        invitation = _get_invitation(info.context.workspace.pk, input.invitation_id)
        invitation.revoke()
        return RevokeInvitationPayload(success=True, errors=[])

    @strawberry.mutation
    @catch_domain_errors(AcceptInvitationPayload)
    def accept_workspace_invitation(
        self,
        info: Info,
        input: AcceptWorkspaceInvitationInput,
    ) -> AcceptInvitationPayload:
        user = _authenticated_user(info)
        invitation = Invitation.get_by_token_or_raise(input.token)
        member = invitation.accept(user)
        return AcceptInvitationPayload(
            success=True, errors=[], member=cast("WorkspaceMemberType", member)
        )

    @strawberry.mutation
    @catch_domain_errors(TransferOwnershipPayload)
    @workspace_scoped
    @requires_role(Action.MEMBERS_TRANSFER_OWNERSHIP)
    def transfer_workspace_ownership(
        self, info: Info, input: TransferWorkspaceOwnershipInput
    ) -> TransferOwnershipPayload:
        user_id = parse_int_id(input.user_id, expected_type="ViewerUserType", field="user_id")
        workspace = info.context.workspace
        workspace.transfer_ownership_to_user_id(user_id)
        workspace.refresh_from_db()
        return TransferOwnershipPayload(
            success=True, errors=[], workspace=cast("WorkspaceType", workspace)
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.MEMBERS_REMOVE)
    @catch_domain_errors(RemoveMemberPayload)
    def remove_workspace_member(self, info: Info, member_id: strawberry.ID) -> RemoveMemberPayload:
        workspace = info.context.workspace
        workspace.remove_member_by_id(member_id)
        return RemoveMemberPayload(success=True, errors=[])

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.MEMBERS_UPDATE_ROLE)
    @catch_domain_errors(UpdateMemberRolePayload)
    def update_workspace_member_role(
        self, info: Info, input: UpdateMemberRoleInput
    ) -> UpdateMemberRolePayload:
        member = info.context.workspace.change_member_role(input.member_id, input.role)
        return UpdateMemberRolePayload(
            success=True, errors=[], member=cast("WorkspaceMemberType", member)
        )
