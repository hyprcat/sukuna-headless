from __future__ import annotations

import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.core.decorators import requires_role, workspace_scoped
from apps.insights.api.types import CategoryCount, InsightSummary, InsightType
from apps.insights.models import Insight


@strawberry.type
class InsightQuery:
    @strawberry_django.connection(DjangoListConnection[InsightType])
    @workspace_scoped
    @requires_role(Action.INSIGHTS_READ)
    def insights(
        self,
        info: Info,
        category: str | None = None,
        status: str | None = None,
    ) -> list[Insight]:
        return Insight.list_for_workspace(  # type: ignore[return-value]
            info.context.workspace.pk,
            category=category,
            status=status,
        )

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.INSIGHTS_READ)
    def insight(self, info: Info, id: strawberry.ID) -> InsightType | None:
        return Insight.get_for_workspace(info.context.workspace.pk, id)  # type: ignore[return-value]

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.INSIGHTS_READ)
    def insight_summary(self, info: Info) -> InsightSummary:
        data = Insight.summary_for_workspace(info.context.workspace.pk)
        return InsightSummary(
            total_active=data["total_active"],
            total_pinned=data["total_pinned"],
            by_category=[
                CategoryCount(category=row["category"], count=row["count"])
                for row in data["by_category"]
            ],
        )
