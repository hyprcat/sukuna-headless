from __future__ import annotations

import factory
from django.utils import timezone

from apps.insights.models import Insight, InsightCategory, InsightStatus
from apps.workspaces.factories import WorkspaceFactory


class InsightFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Insight

    workspace = factory.SubFactory(WorkspaceFactory)
    category = InsightCategory.QUALITY_ISSUE
    title = factory.Sequence(lambda n: f"Insight #{n}")
    body = factory.Faker("paragraph")
    status = InsightStatus.ACTIVE
    affected_agent_ids = factory.LazyFunction(list)
    affected_run_ids = factory.LazyFunction(list)
    affected_end_user_ids = factory.LazyFunction(list)

    class Params:
        pinned = factory.Trait(
            status=InsightStatus.PINNED,
            pinned_at=factory.LazyFunction(timezone.now),
        )
        dismissed = factory.Trait(
            status=InsightStatus.DISMISSED,
            dismissed_at=factory.LazyFunction(timezone.now),
        )
