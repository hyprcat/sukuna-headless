from __future__ import annotations

import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.end_users.api.types import EndUserType
from apps.end_users.models import EndUser


@strawberry.type
class EndUserQuery:
    @strawberry_django.connection(DjangoListConnection[EndUserType])
    @workspace_scoped
    @requires_role(Action.END_USERS_READ)
    @requires_scope("end_users:read")
    def end_users(
        self,
        info: Info,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> list[EndUser]:
        return EndUser.for_workspace(info.context.workspace.pk, search=search, is_active=is_active)  # type: ignore[return-value]

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.END_USERS_READ)
    @requires_scope("end_users:read")
    def end_user(self, info: Info, id: strawberry.ID) -> EndUserType | None:
        pk = parse_int_id(id, expected_type="EndUserType")
        return EndUser.get_for_workspace(info.context.workspace.pk, pk)  # type: ignore[return-value]
