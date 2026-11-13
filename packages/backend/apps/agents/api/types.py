from __future__ import annotations

from datetime import datetime
from typing import cast

import strawberry
import strawberry_django
from django.db.models import Count
from strawberry import relay

from apps.agents.models import Agent
from apps.core.api.types import MutationResult
from apps.knowledge.api.types import KnowledgeType
from apps.policies.api.types import PolicyType
from apps.tools.api.types import ToolType


@strawberry_django.type(Agent)
class AgentType(relay.Node):
    name: str
    description: str
    system_prompt: str
    default_model_tier: str
    is_active: bool
    webhook_url: str
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None

    tools: list[ToolType]

    @strawberry_django.field(prefetch_related=["knowledge_bases"])
    def knowledge(self) -> list[KnowledgeType]:
        agent = cast("Agent", self)
        return list(agent.knowledge_bases.all())  # type: ignore[arg-type]

    @strawberry_django.field(annotate=Count("tools", distinct=True))
    def tools_count(self) -> int:
        return int(getattr(self, "tools_count", 0))

    @strawberry_django.field(annotate=Count("knowledge_bases", distinct=True))
    def knowledge_count(self) -> int:
        return int(getattr(self, "knowledge_count", 0))

    @strawberry_django.field(
        select_related=["policy_override"],
        prefetch_related=["workspace__policies"],
    )
    def policy(self) -> list[PolicyType]:
        agent = cast("Agent", self)
        return cast("list[PolicyType]", list(agent.effective_policies()))


@strawberry.type
class CreateAgentPayload(MutationResult):
    agent: AgentType | None = None


@strawberry.type
class DeactivateAgentPayload(MutationResult):
    agent: AgentType | None = None


@strawberry.type
class ActivateAgentPayload(MutationResult):
    agent: AgentType | None = None


@strawberry.type
class UpdateAgentPayload(MutationResult):
    agent: AgentType | None = None


@strawberry.type
class CloneAgentPayload(MutationResult):
    agent: AgentType | None = None


@strawberry.type
class AssignToolPayload(MutationResult):
    agent: AgentType | None = None


@strawberry.type
class UnassignToolPayload(MutationResult):
    agent: AgentType | None = None


@strawberry.type
class AssignKnowledgePayload(MutationResult):
    agent: AgentType | None = None


@strawberry.type
class UnassignKnowledgePayload(MutationResult):
    agent: AgentType | None = None
