from __future__ import annotations

import strawberry
from strawberry.types import Info

from apps.accounts.models import User
from apps.api_keys.principals import ApiKeyPrincipal, SessionPrincipal
from apps.workspaces.api.types import WorkspaceType
from apps.workspaces.models import Workspace
from apps.workspaces.models.member import WorkspaceMember


@strawberry.type
class ViewerUserType:
    id: strawberry.ID
    email: str
    full_name: str
    is_email_verified: bool


@strawberry.type
class ViewerWorkspaceType:
    id: strawberry.ID
    name: str
    slug: str
    role: str


@strawberry.type
class ViewerType:
    user: ViewerUserType
    workspaces: list[ViewerWorkspaceType]
    current_workspace: WorkspaceType | None


def _authenticated_user(request: object) -> User | None:
    if isinstance(getattr(request, "principal", None), ApiKeyPrincipal):
        return None
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    return user if isinstance(user, User) else None


def _build_viewer_user(user: User) -> ViewerUserType:
    return ViewerUserType(
        id=strawberry.ID(str(user.pk)),
        email=user.email,
        full_name=user.full_name,
        is_email_verified=user.is_email_verified,
    )


def _build_viewer_workspaces(user: User) -> list[ViewerWorkspaceType]:
    memberships = WorkspaceMember.for_user(user)
    return [
        ViewerWorkspaceType(
            id=strawberry.ID(str(m.workspace_id)),
            name=m.workspace.name,
            slug=m.workspace.slug,
            role=m.role,
        )
        for m in memberships
    ]


def _resolve_current_workspace(request: object, user: User) -> Workspace | None:
    principal = getattr(request, "principal", None)
    if not isinstance(principal, SessionPrincipal):
        return None
    if principal.user.pk != user.pk:
        return None
    return Workspace.get_with_owner(principal.workspace_id)


@strawberry.type
class ViewerQuery:
    @strawberry.field
    def viewer(self, info: Info) -> ViewerType | None:
        user = _authenticated_user(info.context.request)
        if user is None:
            return None
        return ViewerType(
            user=_build_viewer_user(user),
            workspaces=_build_viewer_workspaces(user),
            current_workspace=_resolve_current_workspace(info.context.request, user),  # type: ignore[arg-type]
        )
