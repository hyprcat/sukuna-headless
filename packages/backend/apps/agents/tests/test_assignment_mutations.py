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


ASSIGN_TOOL = """
mutation($agentId: ID!, $toolId: ID!) {
    assignTool(agentId: $agentId, toolId: $toolId) {
        success
        errors { code field message }
        agent { tools { name } }
    }
}
"""


UNASSIGN_TOOL = """
mutation($agentId: ID!, $toolId: ID!) {
    unassignTool(agentId: $agentId, toolId: $toolId) {
        success
        errors { code field message }
        agent { tools { name } }
    }
}
"""


ASSIGN_KNOWLEDGE = """
mutation($agentId: ID!, $knowledgeId: ID!) {
    assignKnowledge(agentId: $agentId, knowledgeId: $knowledgeId) {
        success
        errors { code field message }
        agent { knowledge { name } }
    }
}
"""


UNASSIGN_KNOWLEDGE = """
mutation($agentId: ID!, $knowledgeId: ID!) {
    unassignKnowledge(agentId: $agentId, knowledgeId: $knowledgeId) {
        success
        errors { code field message }
        agent { knowledge { name } }
    }
}
"""


def test_assignment_mutations_accept_relay_ids() -> None:
    agent = AgentFactory()
    tool = ToolFactory(workspace=agent.workspace, name="Search")
    kb = KnowledgeFactory(workspace=agent.workspace, name="Docs")
    variables = {
        "agentId": _gid("AgentType", agent.pk),
        "toolId": _gid("ToolType", tool.pk),
        "knowledgeId": _gid("KnowledgeType", kb.pk),
    }

    assigned_tool = _execute(ASSIGN_TOOL, variables, agent.workspace)
    assigned_knowledge = _execute(ASSIGN_KNOWLEDGE, variables, agent.workspace)
    unassigned_tool = _execute(UNASSIGN_TOOL, variables, agent.workspace)
    unassigned_knowledge = _execute(UNASSIGN_KNOWLEDGE, variables, agent.workspace)

    assert assigned_tool["assignTool"]["agent"]["tools"] == [{"name": "Search"}]
    assert assigned_knowledge["assignKnowledge"]["agent"]["knowledge"] == [{"name": "Docs"}]
    assert unassigned_tool["unassignTool"]["agent"]["tools"] == []
    assert unassigned_knowledge["unassignKnowledge"]["agent"]["knowledge"] == []


def test_assign_tool_rejects_wrong_target_relay_type_as_payload_error() -> None:
    agent = AgentFactory()
    result = _schema.execute_sync(
        ASSIGN_TOOL,
        variable_values={
            "agentId": _gid("AgentType", agent.pk),
            "toolId": _gid("KnowledgeType", 1),
        },
        context_value=_ctx(agent.workspace),
    )

    assert result.errors is None
    data = result.data["assignTool"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "tool_id"


def test_assign_knowledge_rejects_wrong_target_relay_type_as_payload_error() -> None:
    agent = AgentFactory()
    result = _schema.execute_sync(
        ASSIGN_KNOWLEDGE,
        variable_values={
            "agentId": _gid("AgentType", agent.pk),
            "knowledgeId": _gid("ToolType", 1),
        },
        context_value=_ctx(agent.workspace),
    )

    assert result.errors is None
    data = result.data["assignKnowledge"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "knowledge_id"


def test_assignment_mutations_keep_bare_id_contract() -> None:
    sdl = str(_schema)

    assert "assignTool(agentId:" in sdl
    assert "unassignTool(agentId:" in sdl
    assert "assignKnowledge(agentId:" in sdl
    assert "unassignKnowledge(agentId:" in sdl


def _execute(query: str, variables: dict[str, object], workspace: object) -> dict[str, object]:
    result = _schema.execute_sync(query, variable_values=variables, context_value=_ctx(workspace))
    assert result.errors is None
    assert result.data is not None
    payload = next(iter(result.data.values()))
    assert isinstance(payload, dict)
    assert payload["success"] is True
    assert payload["errors"] == []
    return result.data
