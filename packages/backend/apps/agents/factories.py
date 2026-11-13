from __future__ import annotations

from typing import TYPE_CHECKING

import factory

from apps.agents.models import Agent
from apps.agents.models.agent import ModelTier
from apps.knowledge.factories import KnowledgeFactory
from apps.policies.factories import PolicyFactory
from apps.tools.factories import ToolFactory
from apps.workspaces.factories import WorkspaceFactory

if TYPE_CHECKING:
    from apps.workspaces.models import Workspace


class AgentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Agent

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"agent-{n}")
    description = factory.Faker("sentence")
    system_prompt = factory.Faker("paragraph")
    default_model_tier = ModelTier.FREE
    is_active = True

    class Params:
        inactive = factory.Trait(is_active=False)
        pro = factory.Trait(default_model_tier=ModelTier.PRO)
        enterprise = factory.Trait(default_model_tier=ModelTier.ENTERPRISE)

    @classmethod
    def with_full_config(cls, workspace: Workspace | None = None, **kwargs) -> Agent:  # type: ignore[override]
        ws = workspace or WorkspaceFactory()
        policy = PolicyFactory(workspace=ws)
        agent: Agent = cls(workspace=ws, policy_override=policy, **kwargs)
        for i in range(3):
            agent.tools.add(ToolFactory(workspace=ws, name=f"tool-{agent.pk}-{i}"))
            agent.knowledge_bases.add(KnowledgeFactory(workspace=ws, name=f"kb-{agent.pk}-{i}"))
        return agent
