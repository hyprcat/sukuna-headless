from __future__ import annotations

from types import SimpleNamespace

import pytest
import strawberry
from django.db import connection
from django.test.utils import CaptureQueriesContext
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.agents.api.queries import AgentQuery
from apps.agents.factories import AgentFactory
from apps.api_keys.principals import ApiKeyPrincipal
from apps.knowledge.factories import KnowledgeFactory
from apps.policies.factories import PolicyFactory
from apps.tools.factories import ToolFactory
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q(AgentQuery):
    pass


_schema = strawberry.Schema(query=_Q, extensions=[DjangoOptimizerExtension])


def _session_ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: True)
    principal = SimpleNamespace(workspace_id=workspace.pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=workspace, principal=principal)


def _api_key_ctx(workspace: object, scopes: frozenset[str]) -> SimpleNamespace:
    api_key = SimpleNamespace(workspace_id=workspace.pk)
    principal = ApiKeyPrincipal(api_key=api_key, scopes=scopes)  # type: ignore[arg-type]
    return SimpleNamespace(workspace=workspace, principal=principal)


AGENT_DETAIL_QUERY = """
query($id: ID!) {
    agent(id: $id) {
        name
        toolsCount
        knowledgeCount
        tools { name }
        knowledge { name }
        policy { name actionRestrictions }
    }
}
"""


def _global_agent_id(agent: object) -> str:
    return relay.to_base64("AgentType", agent.pk)  # type: ignore[union-attr]


def test_agent_detail_returns_tools_knowledge_and_override_policy() -> None:
    ws = WorkspaceFactory()
    PolicyFactory(workspace=ws, name="Workspace policy")
    override = PolicyFactory(workspace=ws, name="Override", with_restrictions=True)
    agent = AgentFactory(workspace=ws, policy_override=override)
    agent.tools.add(ToolFactory(workspace=ws, name="Lookup"))
    agent.knowledge_bases.add(KnowledgeFactory(workspace=ws, name="Handbook"))

    result = _schema.execute_sync(
        AGENT_DETAIL_QUERY,
        variable_values={"id": _global_agent_id(agent)},
        context_value=_session_ctx(ws),
    )

    assert result.errors is None
    data = result.data["agent"]
    assert data["toolsCount"] == 1
    assert data["knowledgeCount"] == 1
    assert data["tools"] == [{"name": "Lookup"}]
    assert data["knowledge"] == [{"name": "Handbook"}]
    assert data["policy"] == [
        {
            "name": "Override",
            "actionRestrictions": ["Never delete user data", "Never send external emails"],
        }
    ]


def test_agent_detail_query_stays_under_query_budget() -> None:
    ws = WorkspaceFactory()
    agent = AgentFactory(workspace=ws, policy_override=PolicyFactory(workspace=ws))
    agent.tools.add(ToolFactory(workspace=ws))
    agent.knowledge_bases.add(KnowledgeFactory(workspace=ws))

    with CaptureQueriesContext(connection) as queries:
        result = _schema.execute_sync(
            AGENT_DETAIL_QUERY,
            variable_values={"id": _global_agent_id(agent)},
            context_value=_session_ctx(ws),
        )

    assert result.errors is None
    assert len(queries) <= 5


def test_agent_detail_falls_back_to_workspace_policies() -> None:
    ws = WorkspaceFactory()
    PolicyFactory(workspace=ws, name="Policy A")
    PolicyFactory(workspace=ws, name="Policy B")
    agent = AgentFactory(workspace=ws)

    result = _schema.execute_sync(
        AGENT_DETAIL_QUERY,
        variable_values={"id": str(agent.pk)},
        context_value=_session_ctx(ws),
    )

    assert result.errors is None
    policies = {policy["name"] for policy in result.data["agent"]["policy"]}
    assert policies == {"Policy A", "Policy B"}


def test_agent_detail_cannot_select_another_workspace_agent() -> None:
    ws = WorkspaceFactory()
    other_agent = AgentFactory()
    result = _schema.execute_sync(
        AGENT_DETAIL_QUERY,
        variable_values={"id": _global_agent_id(other_agent)},
        context_value=_session_ctx(ws),
    )
    assert result.errors is None
    assert result.data["agent"] is None


def test_agent_detail_rejects_wrong_global_id_type() -> None:
    ws = WorkspaceFactory()
    result = _schema.execute_sync(
        AGENT_DETAIL_QUERY,
        variable_values={"id": relay.to_base64("ToolType", 1)},
        context_value=_session_ctx(ws),
    )
    assert result.errors is None
    assert result.data["agent"] is None


def test_agent_detail_allows_api_key_with_agents_read_scope() -> None:
    ws = WorkspaceFactory()
    agent = AgentFactory(workspace=ws)
    result = _schema.execute_sync(
        AGENT_DETAIL_QUERY,
        variable_values={"id": _global_agent_id(agent)},
        context_value=_api_key_ctx(ws, frozenset({"agents:read"})),
    )
    assert result.errors is None
    assert result.data["agent"]["name"] == agent.name


def test_agent_detail_rejects_api_key_without_agents_read_scope() -> None:
    ws = WorkspaceFactory()
    agent = AgentFactory(workspace=ws)
    result = _schema.execute_sync(
        AGENT_DETAIL_QUERY,
        variable_values={"id": _global_agent_id(agent)},
        context_value=_api_key_ctx(ws, frozenset({"tools:read"})),
    )
    assert result.errors is not None
    assert "agents:read" in result.errors[0].message
