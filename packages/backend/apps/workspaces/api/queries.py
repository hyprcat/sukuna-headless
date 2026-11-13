from __future__ import annotations

from typing import cast

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.core.decorators import requires_role, workspace_scoped
from apps.workspaces.api.types import InvitationType, WorkspaceMemberType, WorkspaceType
from apps.workspaces.models import Invitation, Workspace
from apps.workspaces.models.member import WorkspaceMember


def _scoped_workspace_pk(context_pk: int, requested_id: strawberry.ID | None) -> int | None:
    if requested_id is None:
        return context_pk
    return context_pk if str(requested_id) == str(context_pk) else None


@strawberry.type
class WorkspaceQuery:
    @strawberry.field
    @workspace_scoped
    @requires_role(Action.WORKSPACE_READ)
    def workspace(self, info: Info, id: strawberry.ID | None = None) -> WorkspaceType | None:
        pk = _scoped_workspace_pk(info.context.workspace.pk, id)
        if pk is None:
            return None
        workspace = Workspace.get_with_owner(pk)
        return cast("WorkspaceType", workspace)

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.MEMBERS_READ)
    def workspace_members(self, info: Info) -> list[WorkspaceMemberType]:
        members = list(WorkspaceMember.for_workspace(info.context.workspace.pk))
        return cast("list[WorkspaceMemberType]", members)

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.MEMBERS_READ)
    def pending_invitations(self, info: Info) -> list[InvitationType]:
        invitations = list(Invitation.pending_for_workspace(info.context.workspace.pk))
        return cast("list[InvitationType]", invitations)
