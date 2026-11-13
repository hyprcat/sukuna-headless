from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.db import models

if TYPE_CHECKING:
    from apps.insights.models.insight import Insight  # noqa: F401 — QuerySet generic


class InsightCategoryCountData(TypedDict):
    category: str
    count: int


class InsightSummaryData(TypedDict):
    total_active: int
    total_pinned: int
    by_category: list[InsightCategoryCountData]


class InsightAffectedData(TypedDict, total=False):
    affected_agent_ids: list[int]
    affected_run_ids: list[str]
    affected_end_user_ids: list[int]


class InsightCategory(models.TextChoices):
    CAPABILITY_GAP = "capability_gap"
    TIER_OPTIMIZATION = "tier_optimization"
    QUALITY_ISSUE = "quality_issue"
    SCHEDULE_HEALTH = "scheduled_task_health"


class InsightStatus(models.TextChoices):
    ACTIVE = "active"
    DISMISSED = "dismissed"
    PINNED = "pinned"


class InsightQuerySet(models.QuerySet["Insight"]):
    def for_workspace(self, workspace_id: int) -> InsightQuerySet:
        return self.filter(workspace_id=workspace_id)

    def active(self) -> InsightQuerySet:
        return self.filter(status=InsightStatus.ACTIVE)

    def pinned(self) -> InsightQuerySet:
        return self.filter(status=InsightStatus.PINNED)

    def visible(self) -> InsightQuerySet:
        return self.exclude(status=InsightStatus.DISMISSED)

    def by_category(self, category: str) -> InsightQuerySet:
        return self.filter(category=category)
