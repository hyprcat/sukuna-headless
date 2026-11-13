from __future__ import annotations

from types import SimpleNamespace

import pytest
import strawberry
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.agents.api.mutations import AgentMutation
from apps.agents.factories import AgentFactory
from apps.knowledge.factories import KnowledgeFactory
from apps.tools.factories import ToolFactory
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q:
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class _M(AgentMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M, extensions=[DjangoOptimizerExtension])


def _ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: True)
    principal = SimpleNamespace(workspace_id=workspace.pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=workspace, principal=principal)


def _gid(type_name: str, pk: object) -> str:
    return relay.to_base64(type_name, pk)


CREATE_AGENT = """
mutation($input: CreateAgentInput!) {
    createAgent(input: $input) {
        success
        errors { code field message }
        agent { name }
    }
}
"""


def test_create_agent_duplicate_name_returns_mutation_error() -> None:
    ws = WorkspaceFactory()
    AgentFactory(workspace=ws, name="Support")

    result = _schema.execute_sync(
        CREATE_AGENT,
        variable_values={"input": {"name": "Support"}},
        context_value=_ctx(ws),
    )

    assert result.errors is None
    data = result.data["createAgent"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


ACTIVATE_AGENT = """
mutation($id: ID!) {
    activateAgent(id: $id) {
        success
        errors { code field message }
        agent { isActive }
    }
}
"""


def test_activate_agent_accepts_relay_global_id() -> None:
    agent = AgentFactory(inactive=True)

    result = _schema.execute_sync(
        ACTIVATE_AGENT,
        variable_values={"id": _gid("AgentType", agent.pk)},
        context_value=_ctx(agent.workspace),
    )

    assert result.errors is None
    assert result.data["activateAgent"]["success"] is True
    assert result.data["activateAgent"]["agent"]["isActive"] is True


CLONE_AGENT = """
mutation($input: CloneAgentInput!) {
    cloneAgent(input: $input) {
        success
        errors { code field message }
        agent {
            name
            tools { name }
            knowledge { name }
        }
    }
}
"""


def test_clone_agent_schema_uses_input_contract() -> None:
    sdl = str(_schema)

    assert "cloneAgent(input:" in sdl
    assert "cloneAgent(id:" not in sdl
    assert "input CloneAgentInput" in sdl


def test_clone_agent_accepts_input_and_relay_global_id() -> None:
    agent = AgentFactory()
    agent.tools.add(ToolFactory(workspace=agent.workspace, name="Search"))
    agent.knowledge_bases.add(KnowledgeFactory(workspace=agent.workspace, name="Docs"))

    result = _schema.execute_sync(
        CLONE_AGENT,
        variable_values={"input": {"id": _gid("AgentType", agent.pk), "newName": "Support copy"}},
        context_value=_ctx(agent.workspace),
    )

    assert result.errors is None
    data = result.data["cloneAgent"]
    assert data["success"] is True
    assert data["agent"] == {
        "name": "Support copy",
        "tools": [{"name": "Search"}],
        "knowledge": [{"name": "Docs"}],
    }


def test_clone_agent_rejects_wrong_relay_id_type_as_payload_error() -> None:
    ws = WorkspaceFactory()

    result = _schema.execute_sync(
        CLONE_AGENT,
        variable_values={"input": {"id": _gid("ToolType", 1), "newName": "Copy"}},
        context_value=_ctx(ws),
    )

    assert result.errors is None
    data = result.data["cloneAgent"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "id"


def test_clone_agent_duplicate_name_returns_mutation_error() -> None:
    agent = AgentFactory(name="Original")
    AgentFactory(workspace=agent.workspace, name="Taken")

    result = _schema.execute_sync(
        CLONE_AGENT,
        variable_values={"input": {"id": agent.pk, "newName": "Taken"}},
        context_value=_ctx(agent.workspace),
    )

    assert result.errors is None
    data = result.data["cloneAgent"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


ASSIGN_TOOL = """
mutation($agentId: ID!, $toolId: ID!) {
    assignTool(agentId: $agentId, toolId: $toolId) {
        success
        errors { code field message }
        agent { tools { name } }
    }
}
"""


def test_assign_tool_rejects_cross_workspace_relay_id() -> None:
    agent = AgentFactory()
    other_tool = ToolFactory(name="Other")

    result = _schema.execute_sync(
        ASSIGN_TOOL,
        variable_values={
            "agentId": _gid("AgentType", agent.pk),
            "toolId": _gid("ToolType", other_tool.pk),
        },
        context_value=_ctx(agent.workspace),
    )

    assert result.errors is None
    data = result.data["assignTool"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "NOT_FOUND"
