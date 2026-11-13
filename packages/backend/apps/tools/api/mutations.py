from __future__ import annotations

from typing import Any, cast

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.tools.api.types import (
    ActivateToolPayload,
    CreateToolPayload,
    DeactivateToolPayload,
    UpdateToolPayload,
)
from apps.tools.models import Tool


def _get_tool(workspace_pk: int, tool_id: str) -> Tool:
    pk = parse_int_id(tool_id, expected_type="ToolType")
    return Tool.get_for_workspace_or_raise(workspace_pk, pk)


@strawberry.input
class CreateToolInput:
    name: str
    description: str = ""
    parameters_schema: strawberry.scalars.JSON | None = strawberry.UNSET
    execution_endpoint: str = ""
    is_sensitive: bool = False


@strawberry.input
class UpdateToolInput:
    name: str | None = strawberry.UNSET
    description: str | None = strawberry.UNSET
    parameters_schema: strawberry.scalars.JSON | None = strawberry.UNSET
    execution_endpoint: str | None = strawberry.UNSET
    is_sensitive: bool | None = strawberry.UNSET


@strawberry.type
class ToolMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.TOOLS_WRITE)
    @requires_scope("tools:write")
    @catch_domain_errors(CreateToolPayload)
    def create_tool(self, info: Info, input: CreateToolInput) -> CreateToolPayload:
        schema: dict[str, Any] = {}
        if input.parameters_schema is not strawberry.UNSET and input.parameters_schema is not None:
            schema = cast("dict[str, Any]", input.parameters_schema)
        tool = Tool.create_for_workspace(
            info.context.workspace.pk,
            name=input.name,
            description=input.description,
            parameters_schema=schema,
            execution_endpoint=input.execution_endpoint,
            is_sensitive=input.is_sensitive,
        )
        return CreateToolPayload(success=True, errors=[], tool=tool)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.TOOLS_DELETE)
    @requires_scope("tools:write")
    @catch_domain_errors(DeactivateToolPayload)
    def deactivate_tool(self, info: Info, id: strawberry.ID) -> DeactivateToolPayload:
        tool = _get_tool(info.context.workspace.pk, id)
        tool.deactivate()
        return DeactivateToolPayload(success=True, errors=[], tool=tool)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.TOOLS_WRITE)
    @requires_scope("tools:write")
    @catch_domain_errors(ActivateToolPayload)
    def activate_tool(self, info: Info, id: strawberry.ID) -> ActivateToolPayload:
        tool = _get_tool(info.context.workspace.pk, id)
        tool.activate()
        return ActivateToolPayload(success=True, errors=[], tool=tool)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.TOOLS_WRITE)
    @requires_scope("tools:write")
    @catch_domain_errors(UpdateToolPayload)
    def update_tool(
        self, info: Info, id: strawberry.ID, input: UpdateToolInput
    ) -> UpdateToolPayload:
        tool = _get_tool(info.context.workspace.pk, id)
        fields = ("name", "description", "parameters_schema", "execution_endpoint", "is_sensitive")
        provided = {
            k: getattr(input, k) for k in fields if getattr(input, k) is not strawberry.UNSET
        }
        tool.update(**provided)
        return UpdateToolPayload(success=True, errors=[], tool=tool)  # type: ignore[arg-type]
