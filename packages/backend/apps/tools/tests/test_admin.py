from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.tools.admin.tool import ToolAdmin
from apps.tools.factories import ToolFactory
from apps.tools.models import Tool
from apps.workspaces.factories import UserFactory

pytestmark = pytest.mark.django_db


def _staff_user():
    return UserFactory(is_staff=True)


def _grant_tool_perm(user, codename: str) -> None:
    permission = Permission.objects.get(content_type__app_label="tools", codename=codename)
    user.user_permissions.add(permission)


def test_tool_admin_matches_operational_surface_claim() -> None:
    request = RequestFactory().get("/admin/tools/tool/")
    request.user = _staff_user()
    model_admin = ToolAdmin(Tool, admin.site)

    assert "is_sensitive" in model_admin.list_filter
    assert "activate_tool" in model_admin.actions_detail
    assert "deactivate_tool" in model_admin.actions_detail
    assert "test_endpoint" in model_admin.actions_detail
    assert not model_admin.has_delete_permission(request, ToolFactory())


def test_activate_tool_action_requires_change_permission(client: Client) -> None:
    tool = ToolFactory(inactive=True)
    client.force_login(_staff_user())

    response = client.get(reverse("admin:tools_tool_activate_tool", args=[tool.pk]))

    tool.refresh_from_db()
    assert response.status_code == 403
    assert tool.is_active is False


def test_activate_tool_action_activates_and_redirects(client: Client) -> None:
    tool = ToolFactory(inactive=True)
    user = _staff_user()
    _grant_tool_perm(user, "change_tool")
    client.force_login(user)

    response = client.get(reverse("admin:tools_tool_activate_tool", args=[tool.pk]))

    tool.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:tools_tool_change", args=[tool.pk])
    assert tool.is_active is True


def test_deactivate_tool_action_deactivates_and_redirects(client: Client) -> None:
    tool = ToolFactory()
    user = _staff_user()
    _grant_tool_perm(user, "change_tool")
    client.force_login(user)

    response = client.get(reverse("admin:tools_tool_deactivate_tool", args=[tool.pk]))

    tool.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:tools_tool_change", args=[tool.pk])
    assert tool.is_active is False
    assert tool.deactivated_at is not None


def test_test_endpoint_action_requires_view_permission(client: Client) -> None:
    tool = ToolFactory()
    client.force_login(_staff_user())

    response = client.get(reverse("admin:tools_tool_test_endpoint", args=[tool.pk]))

    assert response.status_code == 403


def test_test_endpoint_action_reports_schema_result(client: Client) -> None:
    tool = ToolFactory(
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    user = _staff_user()
    _grant_tool_perm(user, "view_tool")
    client.force_login(user)

    response = client.get(reverse("admin:tools_tool_test_endpoint", args=[tool.pk]))

    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert response.status_code == 302
    assert response.url == reverse("admin:tools_tool_change", args=[tool.pk])
    assert messages == ["Empty payload fails schema: 'query' is a required property"]
