from __future__ import annotations

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.agents.api.types import (
    ActivateAgentPayload,
    AssignKnowledgePayload,
    AssignToolPayload,
    CloneAgentPayload,
    CreateAgentPayload,
    DeactivateAgentPayload,
    UnassignKnowledgePayload,
    UnassignToolPayload,
    UpdateAgentPayload,
)
from apps.agents.models import Agent
from apps.core.api.ids import parse_int_id
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.knowledge.models import Knowledge
from apps.tools.models import Tool


def _get_agent(workspace_pk: int, agent_id: str) -> Agent:
    pk = parse_int_id(agent_id, expected_type="AgentType")
    return Agent.objects.get_for_workspace_or_raise(workspace_pk, pk)


def _get_tool(workspace_pk: int, tool_id: str) -> Tool:
    pk = parse_int_id(tool_id, expected_type="ToolType", field="tool_id")
    return Tool.get_for_workspace_or_raise(workspace_pk, pk)


def _get_knowledge(workspace_pk: int, knowledge_id: str) -> Knowledge:
    pk = parse_int_id(knowledge_id, expected_type="KnowledgeType", field="knowledge_id")
    return Knowledge.get_for_workspace_or_raise(workspace_pk, pk)


@strawberry.input
class CreateAgentInput:
    name: str
    description: str = ""
    system_prompt: str = ""
    default_model_tier: str = "free"
    webhook_url: str = ""


@strawberry.input
class UpdateAgentInput:
    name: str | None = strawberry.UNSET
    description: str | None = strawberry.UNSET
    system_prompt: str | None = strawberry.UNSET
    default_model_tier: str | None = strawberry.UNSET
    webhook_url: str | None = strawberry.UNSET


@strawberry.input
class CloneAgentInput:
    id: strawberry.ID
    new_name: str


@strawberry.type
class AgentMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_WRITE)
    @requires_scope("agents:write")
    @catch_domain_errors(CreateAgentPayload)
    def create_agent(self, info: Info, input: CreateAgentInput) -> CreateAgentPayload:
        agent = Agent.objects.create_for_workspace(
            info.context.workspace.pk,
            name=input.name,
            description=input.description,
            system_prompt=input.system_prompt,
            default_model_tier=input.default_model_tier,
            webhook_url=input.webhook_url,
        )
        return CreateAgentPayload(success=True, errors=[], agent=agent)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_DELETE)
    @requires_scope("agents:write")
    @catch_domain_errors(DeactivateAgentPayload)
    def deactivate_agent(self, info: Info, id: strawberry.ID) -> DeactivateAgentPayload:
        agent = _get_agent(info.context.workspace.pk, id)
        agent.deactivate()
        return DeactivateAgentPayload(success=True, errors=[], agent=agent)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_WRITE)
    @requires_scope("agents:write")
    @catch_domain_errors(ActivateAgentPayload)
    def activate_agent(self, info: Info, id: strawberry.ID) -> ActivateAgentPayload:
        agent = _get_agent(info.context.workspace.pk, id)
        agent.activate()
        return ActivateAgentPayload(success=True, errors=[], agent=agent)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_WRITE)
    @requires_scope("agents:write")
    @catch_domain_errors(UpdateAgentPayload)
    def update_agent(
        self, info: Info, id: strawberry.ID, input: UpdateAgentInput
    ) -> UpdateAgentPayload:
        agent = _get_agent(info.context.workspace.pk, id)
        provided = {
            k: getattr(input, k)
            for k in ("name", "description", "system_prompt", "default_model_tier", "webhook_url")
            if getattr(input, k) is not strawberry.UNSET
        }
        agent.update(**provided)
        return UpdateAgentPayload(success=True, errors=[], agent=agent)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_WRITE)
    @requires_scope("agents:write")
    @catch_domain_errors(CloneAgentPayload)
    def clone_agent(self, info: Info, input: CloneAgentInput) -> CloneAgentPayload:
        agent = _get_agent(info.context.workspace.pk, input.id)
        clone = agent.clone(input.new_name)
        return CloneAgentPayload(success=True, errors=[], agent=clone)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_WRITE)
    @requires_scope("agents:write")
    @catch_domain_errors(AssignToolPayload)
    def assign_tool(
        self, info: Info, agent_id: strawberry.ID, tool_id: strawberry.ID
    ) -> AssignToolPayload:
        ws = info.context.workspace.pk
        agent = _get_agent(ws, agent_id)
        tool = _get_tool(ws, tool_id)
        agent.assign_tool(tool)
        return AssignToolPayload(success=True, errors=[], agent=agent)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_WRITE)
    @requires_scope("agents:write")
    @catch_domain_errors(UnassignToolPayload)
    def unassign_tool(
        self, info: Info, agent_id: strawberry.ID, tool_id: strawberry.ID
    ) -> UnassignToolPayload:
        ws = info.context.workspace.pk
        agent = _get_agent(ws, agent_id)
        tool = _get_tool(ws, tool_id)
        agent.remove_tool(tool)
        return UnassignToolPayload(success=True, errors=[], agent=agent)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_WRITE)
    @requires_scope("agents:write")
    @catch_domain_errors(AssignKnowledgePayload)
    def assign_knowledge(
        self, info: Info, agent_id: strawberry.ID, knowledge_id: strawberry.ID
    ) -> AssignKnowledgePayload:
        ws = info.context.workspace.pk
        agent = _get_agent(ws, agent_id)
        kb = _get_knowledge(ws, knowledge_id)
        agent.assign_knowledge(kb)
        return AssignKnowledgePayload(success=True, errors=[], agent=agent)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.AGENTS_WRITE)
    @requires_scope("agents:write")
    @catch_domain_errors(UnassignKnowledgePayload)
    def unassign_knowledge(
        self, info: Info, agent_id: strawberry.ID, knowledge_id: strawberry.ID
    ) -> UnassignKnowledgePayload:
        ws = info.context.workspace.pk
        agent = _get_agent(ws, agent_id)
        kb = _get_knowledge(ws, knowledge_id)
        agent.remove_knowledge(kb)
        return UnassignKnowledgePayload(success=True, errors=[], agent=agent)  # type: ignore[arg-type]
