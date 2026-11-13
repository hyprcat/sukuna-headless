from __future__ import annotations

from datetime import datetime

import strawberry
import strawberry_django
from strawberry import relay

from apps.core.api.types import MutationResult
from apps.insights.models import Insight


@strawberry_django.type(Insight)
class InsightType(relay.Node):
    category: str
    title: str
    body: str
    status: str
    affected_agent_ids: strawberry.scalars.JSON
    affected_run_ids: strawberry.scalars.JSON
    affected_end_user_ids: strawberry.scalars.JSON
    created_at: datetime
    dismissed_at: datetime | None
    pinned_at: datetime | None


@strawberry.type
class CategoryCount:
    category: str
    count: int


@strawberry.type
class InsightSummary:
    total_active: int
    total_pinned: int
    by_category: list[CategoryCount]


@strawberry.type
class DismissInsightPayload(MutationResult):
    insight: InsightType | None = None


@strawberry.type
class PinInsightPayload(MutationResult):
    insight: InsightType | None = None


@strawberry.type
class UnpinInsightPayload(MutationResult):
    insight: InsightType | None = None
