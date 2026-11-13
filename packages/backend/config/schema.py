from __future__ import annotations

import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.accounts.api.queries import ViewerQuery
from apps.agents.api.mutations import AgentMutation
from apps.agents.api.queries import AgentQuery
from apps.api_keys.api.mutations import APIKeyMutation
from apps.api_keys.api.queries import APIKeyQuery
from apps.billing.api.mutations import BillingMutation
from apps.billing.api.queries import BillingQuery
from apps.end_users.api.mutations import EndUserMutation
from apps.end_users.api.queries import EndUserQuery
from apps.insights.api.mutations import InsightMutation
from apps.insights.api.queries import InsightQuery
from apps.knowledge.api.mutations import KnowledgeMutation
from apps.knowledge.api.queries import KnowledgeQuery
from apps.policies.api.mutations import PolicyMutation
from apps.policies.api.queries import PolicyQuery
from apps.runs.api.mutations import RatingMutation, RunMutation
from apps.runs.api.queries import RatingQuery, RunQuery
from apps.schedules.api.mutations import ScheduleMutation
from apps.schedules.api.queries import ScheduleQuery
from apps.tools.api.mutations import ToolMutation
from apps.tools.api.queries import ToolQuery
from apps.workspaces.api.mutations import WorkspaceMutation
from apps.workspaces.api.queries import WorkspaceQuery


@strawberry.type
class Query(
    AgentQuery,
    APIKeyQuery,
    BillingQuery,
    EndUserQuery,
    InsightQuery,
    KnowledgeQuery,
    PolicyQuery,
    RatingQuery,
    RunQuery,
    ScheduleQuery,
    ToolQuery,
    ViewerQuery,
    WorkspaceQuery,
):
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class Mutation(
    AgentMutation,
    APIKeyMutation,
    BillingMutation,
    EndUserMutation,
    InsightMutation,
    KnowledgeMutation,
    PolicyMutation,
    RatingMutation,
    RunMutation,
    ScheduleMutation,
    ToolMutation,
    WorkspaceMutation,
):
    pass


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[DjangoOptimizerExtension],
)
