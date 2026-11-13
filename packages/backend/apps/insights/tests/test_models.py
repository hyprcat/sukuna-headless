from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.exceptions import Conflict
from apps.insights.factories import InsightFactory
from apps.insights.models import Insight, InsightCategory, InsightStatus
from apps.workspaces.factories import UserFactory, WorkspaceFactory

pytestmark = pytest.mark.django_db


# -- Generate --


def test_generate_creates_with_defaults() -> None:
    ws = WorkspaceFactory()
    insight = Insight.generate(
        workspace_id=ws.pk,
        category=InsightCategory.CAPABILITY_GAP,
        title="Missing PDF tool",
        body="3 runs failed because no PDF extraction tool is assigned.",
    )
    assert insight.pk is not None
    assert insight.status == InsightStatus.ACTIVE
    assert insight.affected_agent_ids == []


def test_generate_stores_affected_entities() -> None:
    ws = WorkspaceFactory()
    insight = Insight.generate(
        workspace_id=ws.pk,
        category=InsightCategory.TIER_OPTIMIZATION,
        title="Pro tier underused",
        body="End users 1, 2 never hit pro token limits.",
        affected={"affected_end_user_ids": [1, 2], "affected_agent_ids": [10]},
    )
    assert insight.affected_end_user_ids == [1, 2]
    assert insight.affected_agent_ids == [10]


# -- Dismiss --


def test_dismiss_active_insight() -> None:
    user = UserFactory()
    insight = InsightFactory()
    insight.dismiss(user_id=user.pk)
    insight.refresh_from_db()
    assert insight.status == InsightStatus.DISMISSED
    assert insight.dismissed_at is not None
    assert insight.dismissed_by_id == user.pk


def test_dismiss_pinned_insight_clears_pin_timestamp() -> None:
    user = UserFactory()
    insight = InsightFactory(pinned=True)
    assert insight.pinned_at is not None

    insight.dismiss(user_id=user.pk)

    insight.refresh_from_db()
    assert insight.status == InsightStatus.DISMISSED
    assert insight.pinned_at is None


def test_dismiss_already_dismissed_raises() -> None:
    user = UserFactory()
    insight = InsightFactory(dismissed=True)
    with pytest.raises(Conflict):
        insight.dismiss(user_id=user.pk)


# -- Pin --


def test_pin_active_insight() -> None:
    insight = InsightFactory()
    insight.pin()
    insight.refresh_from_db()
    assert insight.status == InsightStatus.PINNED
    assert insight.pinned_at is not None


def test_pin_dismissed_insight_raises() -> None:
    insight = InsightFactory(dismissed=True)
    with pytest.raises(Conflict):
        insight.pin()


def test_pin_already_pinned_raises() -> None:
    insight = InsightFactory(pinned=True)
    with pytest.raises(Conflict):
        insight.pin()


def test_unpin_pinned_insight() -> None:
    insight = InsightFactory(pinned=True)
    insight.unpin()
    insight.refresh_from_db()
    assert insight.status == InsightStatus.ACTIVE
    assert insight.pinned_at is None


def test_unpin_non_pinned_raises() -> None:
    insight = InsightFactory()
    with pytest.raises(Conflict):
        insight.unpin()


# -- QuerySet --


def test_visible_excludes_dismissed() -> None:
    ws = WorkspaceFactory()
    InsightFactory(workspace=ws)
    InsightFactory(workspace=ws, pinned=True)
    InsightFactory(workspace=ws, dismissed=True)
    assert Insight.objects.for_workspace(ws.pk).visible().count() == 2


def test_by_category_filters() -> None:
    ws = WorkspaceFactory()
    InsightFactory(workspace=ws, category=InsightCategory.QUALITY_ISSUE)
    InsightFactory(workspace=ws, category=InsightCategory.SCHEDULE_HEALTH)
    qs = Insight.objects.for_workspace(ws.pk).by_category(InsightCategory.QUALITY_ISSUE)
    assert qs.count() == 1


# -- Validation --


def test_save_rejects_invalid_category() -> None:
    insight = InsightFactory.build(category="unknown")
    with pytest.raises(ValidationError, match="category"):
        insight.save()


def test_save_rejects_invalid_status() -> None:
    insight = InsightFactory.build(status="unknown")
    with pytest.raises(ValidationError, match="status"):
        insight.save()


def test_save_rejects_non_list_affected_agent_ids() -> None:
    insight = InsightFactory.build(affected_agent_ids={"id": 1})
    with pytest.raises(ValidationError, match="affected_agent_ids"):
        insight.save()


def test_save_rejects_malformed_run_ids() -> None:
    insight = InsightFactory.build(affected_run_ids=["not-a-uuid"])
    with pytest.raises(ValidationError, match="affected_run_ids"):
        insight.save()


def test_save_accepts_uuid_run_ids() -> None:
    run_id = str(uuid.uuid4())
    insight = InsightFactory(affected_run_ids=[run_id])
    assert insight.affected_run_ids == [run_id]


def test_status_constraint_blocks_queryset_update() -> None:
    insight = InsightFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Insight.objects.filter(pk=insight.pk).update(status="unknown")


def test_category_constraint_blocks_queryset_update() -> None:
    insight = InsightFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Insight.objects.filter(pk=insight.pk).update(category="unknown")


def test_title_constraint_blocks_queryset_update() -> None:
    insight = InsightFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Insight.objects.filter(pk=insight.pk).update(title="")


def test_body_constraint_blocks_queryset_update() -> None:
    insight = InsightFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        Insight.objects.filter(pk=insight.pk).update(body="")
