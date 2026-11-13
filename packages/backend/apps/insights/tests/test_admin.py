from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.insights.admin.insight import InsightAdmin
from apps.insights.factories import InsightFactory
from apps.insights.models import Insight, InsightStatus
from apps.workspaces.factories import UserFactory

pytestmark = pytest.mark.django_db


def _staff_user():
    return UserFactory(is_staff=True)


def _grant_insight_perm(user, codename: str) -> None:
    permission = Permission.objects.get(content_type__app_label="insights", codename=codename)
    user.user_permissions.add(permission)


def test_insight_admin_matches_operational_surface_claim() -> None:
    request = RequestFactory().get("/admin/insights/insight/")
    request.user = _staff_user()
    model_admin = InsightAdmin(Insight, admin.site)

    assert "dismiss_insight" in model_admin.actions_detail
    assert "pin_insight" in model_admin.actions_detail
    assert "unpin_insight" in model_admin.actions_detail
    assert not model_admin.has_delete_permission(request, InsightFactory())


def test_dismiss_action_requires_change_permission(client: Client) -> None:
    insight = InsightFactory()
    client.force_login(_staff_user())

    response = client.get(reverse("admin:insights_insight_dismiss_insight", args=[insight.pk]))

    insight.refresh_from_db()
    assert response.status_code == 403
    assert insight.status == InsightStatus.ACTIVE


def test_dismiss_action_dismisses_and_redirects(client: Client) -> None:
    insight = InsightFactory(pinned=True)
    user = _staff_user()
    _grant_insight_perm(user, "change_insight")
    client.force_login(user)

    response = client.get(reverse("admin:insights_insight_dismiss_insight", args=[insight.pk]))

    insight.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:insights_insight_change", args=[insight.pk])
    assert insight.status == InsightStatus.DISMISSED
    assert insight.pinned_at is None


def test_pin_action_redirects_and_warns_for_dismissed(client: Client) -> None:
    insight = InsightFactory(dismissed=True)
    user = _staff_user()
    _grant_insight_perm(user, "change_insight")
    client.force_login(user)

    response = client.get(reverse("admin:insights_insight_pin_insight", args=[insight.pk]))

    messages = [str(message) for message in get_messages(response.wsgi_request)]
    insight.refresh_from_db()
    assert response.status_code == 302
    assert insight.status == InsightStatus.DISMISSED
    assert messages == ["Dismissed insights cannot be pinned."]


def test_unpin_action_unpins_and_redirects(client: Client) -> None:
    insight = InsightFactory(pinned=True)
    user = _staff_user()
    _grant_insight_perm(user, "change_insight")
    client.force_login(user)

    response = client.get(reverse("admin:insights_insight_unpin_insight", args=[insight.pk]))

    insight.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:insights_insight_change", args=[insight.pk])
    assert insight.status == InsightStatus.ACTIVE
