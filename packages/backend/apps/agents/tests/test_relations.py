from __future__ import annotations

import pytest

from apps.agents.factories import AgentFactory
from apps.agents.models import Agent
from apps.agents.schemas import AgentFormat
from apps.core.exceptions import Conflict, NotFound
from apps.knowledge.factories import KnowledgeFactory
from apps.policies.factories import PolicyFactory
from apps.tools.factories import ToolFactory
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


# -- assign_tool / remove_tool ------------------------------------------------


def test_assign_tool_adds_to_m2m() -> None:
    agent = AgentFactory()
    tool = ToolFactory(workspace=agent.workspace)

    agent.assign_tool(tool)

    assert tool in agent.tools.all()


def test_assign_tool_rejects_cross_workspace() -> None:
    agent = AgentFactory()
    tool = ToolFactory()

    with pytest.raises(Conflict, match="different workspace"):
        agent.assign_tool(tool)


def test_assign_tool_rejects_over_cap() -> None:
    fmt = AgentFormat()
    agent = AgentFactory()
    for i in range(fmt.max_tools_per_agent):
        agent.tools.add(ToolFactory(workspace=agent.workspace, name=f"t-{i}"))

    with pytest.raises(Conflict, match="maximum"):
        agent.assign_tool(ToolFactory(workspace=agent.workspace, name="one-too-many"))


def test_remove_tool_removes_from_m2m() -> None:
    agent = AgentFactory()
    tool = ToolFactory(workspace=agent.workspace)
    agent.tools.add(tool)

    agent.remove_tool(tool)

    assert tool not in agent.tools.all()


def test_remove_tool_rejects_cross_workspace() -> None:
    agent = AgentFactory()
    tool = ToolFactory()

    with pytest.raises(Conflict, match="different workspace"):
        agent.remove_tool(tool)


def test_remove_tool_is_idempotent_without_event(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[object] = []
    agent = AgentFactory()
    tool = ToolFactory(workspace=agent.workspace)

    def fake_record_event(*args: object, **kwargs: object) -> None:
        events.append((args, kwargs))

    monkeypatch.setattr("apps.agents.models.agent.record_event", fake_record_event)

    agent.remove_tool(tool)

    assert events == []


def test_assign_tool_is_idempotent() -> None:
    agent = AgentFactory()
    tool = ToolFactory(workspace=agent.workspace)
    agent.assign_tool(tool)
    agent.assign_tool(tool)

    assert agent.tools.count() == 1


# -- assign_knowledge / remove_knowledge --------------------------------------


def test_assign_knowledge_adds_to_m2m() -> None:
    agent = AgentFactory()
    kb = KnowledgeFactory(workspace=agent.workspace)

    agent.assign_knowledge(kb)

    assert kb in agent.knowledge_bases.all()


def test_assign_knowledge_rejects_cross_workspace() -> None:
    agent = AgentFactory()
    kb = KnowledgeFactory()

    with pytest.raises(Conflict, match="different workspace"):
        agent.assign_knowledge(kb)


def test_assign_knowledge_rejects_over_cap() -> None:
    fmt = AgentFormat()
    agent = AgentFactory()
    for i in range(fmt.max_knowledge_per_agent):
        agent.knowledge_bases.add(KnowledgeFactory(workspace=agent.workspace, name=f"kb-{i}"))

    with pytest.raises(Conflict, match="maximum"):
        agent.assign_knowledge(KnowledgeFactory(workspace=agent.workspace, name="one-too-many"))


def test_remove_knowledge_removes_from_m2m() -> None:
    agent = AgentFactory()
    kb = KnowledgeFactory(workspace=agent.workspace)
    agent.knowledge_bases.add(kb)

    agent.remove_knowledge(kb)

    assert kb not in agent.knowledge_bases.all()


def test_remove_knowledge_rejects_cross_workspace() -> None:
    agent = AgentFactory()
    kb = KnowledgeFactory()

    with pytest.raises(Conflict, match="different workspace"):
        agent.remove_knowledge(kb)


def test_remove_knowledge_is_idempotent_without_event(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[object] = []
    agent = AgentFactory()
    kb = KnowledgeFactory(workspace=agent.workspace)

    def fake_record_event(*args: object, **kwargs: object) -> None:
        events.append((args, kwargs))

    monkeypatch.setattr("apps.agents.models.agent.record_event", fake_record_event)

    agent.remove_knowledge(kb)

    assert events == []


def test_assign_knowledge_is_idempotent() -> None:
    agent = AgentFactory()
    kb = KnowledgeFactory(workspace=agent.workspace)
    agent.assign_knowledge(kb)
    agent.assign_knowledge(kb)

    assert agent.knowledge_bases.count() == 1


# -- effective_policies --------------------------------------------------------


def test_effective_policies_returns_override_when_set() -> None:
    ws = WorkspaceFactory()
    PolicyFactory(workspace=ws, name="workspace-wide")
    override = PolicyFactory(workspace=ws, name="agent-specific")
    agent = AgentFactory(workspace=ws, policy_override=override)

    policies = list(agent.effective_policies())

    assert len(policies) == 1
    assert policies[0] == override


def test_effective_policies_falls_back_to_workspace() -> None:
    ws = WorkspaceFactory()
    p1 = PolicyFactory(workspace=ws, name="policy-a")
    p2 = PolicyFactory(workspace=ws, name="policy-b")
    agent = AgentFactory(workspace=ws)

    policies = set(agent.effective_policies())

    assert policies == {p1, p2}


# -- clone ---------------------------------------------------------------------


def test_clone_copies_scalar_fields() -> None:
    agent = AgentFactory(system_prompt="do things", default_model_tier="pro")
    clone = agent.clone("clone-name")

    assert clone.pk != agent.pk
    assert clone.name == "clone-name"
    assert clone.workspace_id == agent.workspace_id
    assert clone.system_prompt == agent.system_prompt
    assert clone.default_model_tier == agent.default_model_tier


def test_clone_copies_m2m_relations() -> None:
    agent = AgentFactory()
    tool = ToolFactory(workspace=agent.workspace)
    kb = KnowledgeFactory(workspace=agent.workspace)
    agent.tools.add(tool)
    agent.knowledge_bases.add(kb)

    clone = agent.clone("clone-with-rels")

    assert tool in clone.tools.all()
    assert kb in clone.knowledge_bases.all()


def test_clone_rejects_blank_name() -> None:
    agent = AgentFactory()
    with pytest.raises(Conflict, match="blank"):
        agent.clone("  ")


def test_clone_rejects_duplicate_name() -> None:
    agent = AgentFactory(name="original")
    AgentFactory(workspace=agent.workspace, name="taken")

    with pytest.raises(Conflict, match="already exists"):
        agent.clone("taken")


def test_clone_uses_current_source_state() -> None:
    agent = AgentFactory(description="old description")
    Agent.objects.filter(pk=agent.pk).update(description="fresh description")

    clone = agent.clone("fresh-clone")

    assert clone.description == "fresh description"


def test_clone_rejects_deleted_source() -> None:
    agent = AgentFactory()
    agent.delete()

    with pytest.raises(NotFound, match="Agent not found"):
        agent.clone("stale-clone")


# -- with_full_config ----------------------------------------------------------


def test_with_full_config_builds_wired_graph() -> None:
    agent = AgentFactory.with_full_config()

    assert agent.policy_override is not None
    assert agent.tools.count() == 3
    assert agent.knowledge_bases.count() == 3
    assert all(t.workspace_id == agent.workspace_id for t in agent.tools.all())
    assert all(k.workspace_id == agent.workspace_id for k in agent.knowledge_bases.all())
