from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.agents.factories import AgentFactory
from apps.end_users.factories import EndUserFactory
from apps.schedules.admin.execution import ScheduleExecutionAdmin
from apps.schedules.admin.schedule import ScheduleAdmin, ScheduleAdminForm
from apps.schedules.factories import ScheduleExecutionFactory, ScheduleFactory
from apps.schedules.models import Schedule, ScheduleExecution, ScheduleStatus
from apps.workspaces.factories import UserFactory

pytestmark = pytest.mark.django_db


def _staff_user():
    return UserFactory(is_staff=True)


def _grant_schedule_perm(user, codename: str) -> None:
    permission = Permission.objects.get(content_type__app_label="schedules", codename=codename)
    user.user_permissions.add(permission)


def test_schedule_admin_matches_operational_surface_claim() -> None:
    request = RequestFactory().get("/admin/schedules/schedule/")
    request.user = _staff_user()
    model_admin = ScheduleAdmin(Schedule, admin.site)

    assert "pause_schedule" in model_admin.actions_detail
    assert "resume_schedule" in model_admin.actions_detail
    assert "disable_schedule" in model_admin.actions_detail
    assert "failure_handling" in model_admin.list_filter


def test_schedule_admin_form_rejects_cross_workspace_agent() -> None:
    schedule = ScheduleFactory()
    other_agent = AgentFactory()
    data = _schedule_form_data(schedule) | {"agent": other_agent.pk}

    form = ScheduleAdminForm(data=data)

    assert not form.is_valid()
    assert "agent" in form.errors


def test_schedule_admin_form_rejects_cross_workspace_end_user() -> None:
    schedule = ScheduleFactory()
    other_end_user = EndUserFactory()
    data = _schedule_form_data(schedule) | {"target_end_user": other_end_user.pk}

    form = ScheduleAdminForm(data=data)

    assert not form.is_valid()
    assert "target_end_user" in form.errors


def test_schedule_admin_foreign_keys_filter_to_posted_workspace() -> None:
    schedule = ScheduleFactory()
    AgentFactory()
    request = RequestFactory().post("/", data={"workspace": schedule.workspace_id})
    model_admin = ScheduleAdmin(Schedule, admin.site)
    field = Schedule._meta.get_field("agent")

    form_field = model_admin.formfield_for_foreignkey(field, request)

    assert list(form_field.queryset) == [schedule.agent]


def test_pause_schedule_action_requires_change_permission(client: Client) -> None:
    schedule = ScheduleFactory()
    client.force_login(_staff_user())

    response = client.get(reverse("admin:schedules_schedule_pause_schedule", args=[schedule.pk]))

    schedule.refresh_from_db()
    assert response.status_code == 403
    assert schedule.status == ScheduleStatus.ACTIVE


def test_pause_schedule_action_pauses_and_redirects(client: Client) -> None:
    schedule = ScheduleFactory()
    user = _staff_user()
    _grant_schedule_perm(user, "change_schedule")
    client.force_login(user)

    response = client.get(reverse("admin:schedules_schedule_pause_schedule", args=[schedule.pk]))

    schedule.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:schedules_schedule_change", args=[schedule.pk])
    assert schedule.status == ScheduleStatus.PAUSED


def test_resume_schedule_action_resumes_and_redirects(client: Client) -> None:
    schedule = ScheduleFactory(paused=True)
    user = _staff_user()
    _grant_schedule_perm(user, "change_schedule")
    client.force_login(user)

    response = client.get(reverse("admin:schedules_schedule_resume_schedule", args=[schedule.pk]))

    schedule.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:schedules_schedule_change", args=[schedule.pk])
    assert schedule.status == ScheduleStatus.ACTIVE
    assert schedule.next_run_at is not None


def test_disable_schedule_action_disables_and_redirects(client: Client) -> None:
    schedule = ScheduleFactory()
    user = _staff_user()
    _grant_schedule_perm(user, "change_schedule")
    client.force_login(user)

    response = client.get(reverse("admin:schedules_schedule_disable_schedule", args=[schedule.pk]))

    schedule.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("admin:schedules_schedule_change", args=[schedule.pk])
    assert schedule.status == ScheduleStatus.DISABLED


def test_schedule_execution_admin_is_fully_read_only() -> None:
    request = RequestFactory().get("/admin/schedules/scheduleexecution/")
    request.user = _staff_user()
    execution = ScheduleExecutionFactory()
    model_admin = ScheduleExecutionAdmin(ScheduleExecution, admin.site)

    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request, execution)
    assert not model_admin.has_delete_permission(request, execution)


def _schedule_form_data(schedule: Schedule) -> dict[str, object]:
    return {
        "workspace": schedule.workspace_id,
        "name": schedule.name,
        "description": schedule.description,
        "agent": schedule.agent_id,
        "target_end_user": schedule.target_end_user_id,
        "prompt": schedule.prompt,
        "cron_expression": schedule.cron_expression,
        "failure_handling": schedule.failure_handling,
        "output_routing": "[]",
        "status": schedule.status,
    }
