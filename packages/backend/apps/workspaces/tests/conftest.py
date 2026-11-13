from __future__ import annotations

from types import SimpleNamespace

import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.workspaces.api.mutations import WorkspaceMutation
from apps.workspaces.api.queries import WorkspaceQuery
from apps.workspaces.factories import UserFactory


@strawberry.type
class _Q(WorkspaceQuery):
    pass


@strawberry.type
class _M(WorkspaceMutation):
    pass


schema = strawberry.Schema(query=_Q, mutation=_M, extensions=[DjangoOptimizerExtension])


def session_ctx(
    user: object,
    workspace: object | None = None,
    *,
    can_act: bool = True,
) -> SimpleNamespace:
    member = None
    principal = None
    if workspace is not None:
        member = SimpleNamespace(
            workspace_id=workspace.pk,  # type: ignore[union-attr]
            can=lambda _action: can_act,
        )
        principal = SimpleNamespace(
            workspace_id=workspace.pk,  # type: ignore[union-attr]
            member=member,
            scopes=frozenset(),
        )
    request = SimpleNamespace(user=user)
    return SimpleNamespace(
        workspace=workspace,
        principal=principal,
        request=request,
    )


def verified_user() -> object:
    user = UserFactory()
    user.verify_email()
    return user
