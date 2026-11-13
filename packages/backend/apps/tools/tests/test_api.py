from __future__ import annotations

from types import SimpleNamespace

import pytest
import strawberry
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.tools.api.mutations import ToolMutation
from apps.tools.factories import ToolFactory
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q:
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class _M(ToolMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M, extensions=[DjangoOptimizerExtension])


def _ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: True)
    principal = SimpleNamespace(workspace_id=workspace.pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=workspace, principal=principal)


CREATE_TOOL = """
mutation($input: CreateToolInput!) {
    createTool(input: $input) {
        success
        errors { code field message }
        tool { name }
    }
}
"""


def test_create_tool_duplicate_name_returns_mutation_error() -> None:
    ws = WorkspaceFactory()
    ToolFactory(workspace=ws, name="Lookup")

    result = _schema.execute_sync(
        CREATE_TOOL,
        variable_values={
            "input": {
                "name": "Lookup",
                "executionEndpoint": "https://tools.example.com/lookup",
            }
        },
        context_value=_ctx(ws),
    )

    assert result.errors is None
    data = result.data["createTool"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


UPDATE_TOOL = """
mutation($id: ID!, $input: UpdateToolInput!) {
    updateTool(id: $id, input: $input) {
        success
        errors { code field message }
        tool { name }
    }
}
"""


def test_update_tool_accepts_relay_global_id() -> None:
    tool = ToolFactory()

    result = _schema.execute_sync(
        UPDATE_TOOL,
        variable_values={
            "id": relay.to_base64("ToolType", tool.pk),
            "input": {"name": "Renamed"},
        },
        context_value=_ctx(tool.workspace),
    )

    assert result.errors is None
    assert result.data["updateTool"]["success"] is True
    assert result.data["updateTool"]["tool"]["name"] == "Renamed"
