from __future__ import annotations

import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.tools.api.types import ToolType
from apps.tools.models import Tool


@strawberry.type
class ToolQuery:
    @strawberry_django.connection(DjangoListConnection[ToolType])
    @workspace_scoped
    @requires_role(Action.TOOLS_READ)
    @requires_scope("tools:read")
    def tools(
        self,
        info: Info,
        is_active: bool | None = None,
    ) -> list[Tool]:
        return Tool.for_workspace(info.context.workspace.pk, is_active=is_active)  # type: ignore[return-value]

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.TOOLS_READ)
    @requires_scope("tools:read")
    def tool(self, info: Info, id: strawberry.ID) -> ToolType | None:
        pk = parse_int_id(id, expected_type="ToolType")
        return Tool.get_for_workspace(info.context.workspace.pk, pk)  # type: ignore[return-value]
