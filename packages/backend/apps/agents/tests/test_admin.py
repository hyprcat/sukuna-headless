from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.agents.admin.agent import AgentAdmin, AgentAdminForm
from apps.agents.factories import AgentFactory
from apps.agents.models import Agent
from apps.agents.models.agent import ModelTier
from apps.agents.schemas import AgentFormat
from apps.knowledge.factories import KnowledgeFactory
from apps.tools.factories import ToolFactory
from apps.workspaces.factories import UserFactory, WorkspaceFactory

pytestmark = pytest.mark.django_db


def _staff_user():
    return UserFactory(is_staff=True)


def _grant_agent_perm(user, codename: str) -> None:
    permission = Permission.objects.get(content_type__app_label="agents", codename=codename)
    user.user_permissions.add(permission)


def _form_data(workspace, *, tools=(), knowledge=(), name: str = "agent"):
    return {
        "workspace": workspace.pk,
        "name": name,
        "description": "",
        "system_prompt": "",
        "default_model_tier": ModelTier.FREE,
        "policy_override": "",
        "webhook_url": "",
        "is_active": "on",
        "tools": [tool.pk for tool in tools],
        "knowledge_bases": [kb.pk for kb in knowledge],
    }


def test_agent_admin_matches_operational_surface_claim() -> None:
    request = RequestFactory().get("/admin/agents/agent/")
    request.user = _staff_user()
    model_admin = AgentAdmin(Agent, admin.site)

    assert model_admin.form is AgentAdminForm
    assert "activate_agent" in model_admin.actions_detail
    assert "deactivate_agent" in model_admin.actions_detail
    assert "clone_agent" in model_admin.actions_detail
    assert not model_admin.has_delete_permission(request, AgentFactory())


def test_admin_form_rejects_cross_workspace_tool() -> None:
    workspace = WorkspaceFactory()
    tool = ToolFactory()
    form = AgentAdminForm(data=_form_data(workspace, tools=[tool]))

    assert not form.is_valid()
    assert form.errors["tools"] == ["Assignments must belong to the agent workspace."]


def test_admin_form_rejects_cross_workspace_knowledge() -> None:
    workspace = WorkspaceFactory()
    kb = KnowledgeFactory()
    form = AgentAdminForm(data=_form_data(workspace, knowledge=[kb]))

    assert not form.is_valid()
    assert form.errors["knowledge_bases"] == ["Assignments must belong to the agent workspace."]


def test_admin_form_rejects_tool_cap_overflow() -> None:
    fmt = AgentFormat()
    workspace = WorkspaceFactory()
    tools = [
        ToolFactory(workspace=workspace, name=f"tool-{i}")
        for i in range(fmt.max_tools_per_agent + 1)
    ]
    form = AgentAdminForm(data=_form_data(workspace, tools=tools))

    assert not form.is_valid()
    assert form.errors["tools"] == [f"Select at most {fmt.max_tools_per_agent} items."]


def test_agent_admin_limits_m2m_choices_to_agent_workspace() -> None:
    agent = AgentFactory()
    tool = ToolFactory(workspace=agent.workspace)
    other_tool = ToolFactory()
    request = RequestFactory().get(f"/admin/agents/agent/{agent.pk}/change/")
    request.resolver_match = SimpleNamespace(kwargs={"object_id": str(agent.pk)})
    model_admin = AgentAdmin(Agent, admin.site)
    field = Agent._meta.get_field("tools")

    form_field = model_admin.formfield_for_manytomany(field, request)

    assert set(form_field.queryset) == {tool}
    assert other_tool not in form_field.queryset


def test_activate_agent_action_requires_change_permission(client: Client) -> None:
    agent = AgentFactory(inactive=True)
    client.force_login(_staff_user())

    response = client.get(reverse("admin:agents_agent_activate_agent", args=[agent.pk]))

    agent.refresh_from_db()
    assert response.status_code == 403
    assert agent.is_active is False


def test_activate_agent_action_activates_and_redirects(client: Client) -> None:
    agent = AgentFactory(inactive=True)
    user = _staff_user()
    _grant_agent_perm(user, "change_agent")
    client.force_login(user)

    response = client.get(reverse("admin:agents_agent_activate_agent", args=[agent.pk]))

    agent.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:agents_agent_change", args=[agent.pk])
    assert agent.is_active is True


def test_deactivate_agent_action_deactivates_and_redirects(client: Client) -> None:
    agent = AgentFactory()
    user = _staff_user()
    _grant_agent_perm(user, "change_agent")
    client.force_login(user)

    response = client.get(reverse("admin:agents_agent_deactivate_agent", args=[agent.pk]))

    agent.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:agents_agent_change", args=[agent.pk])
    assert agent.is_active is False
    assert agent.deactivated_at is not None


def test_clone_agent_action_clones_with_unique_name(client: Client) -> None:
    agent = AgentFactory(name="alpha")
    AgentFactory(workspace=agent.workspace, name="alpha (copy)")
    user = _staff_user()
    _grant_agent_perm(user, "change_agent")
    client.force_login(user)

    response = client.get(reverse("admin:agents_agent_clone_agent", args=[agent.pk]))

    clone = Agent.objects.get(workspace=agent.workspace, name="alpha (copy) 2")
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert response.status_code == 302
    assert response.url == reverse("admin:agents_agent_change", args=[clone.pk])
    assert messages == ["Cloned as 'alpha (copy) 2'."]
