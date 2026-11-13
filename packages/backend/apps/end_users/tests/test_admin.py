from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.test import RequestFactory

from apps.end_users.admin.end_user import ControlProfileInline, ControlProfileInlineForm
from apps.end_users.factories import EndUserFactory
from apps.end_users.models import ControlProfile, EndUser
from apps.knowledge.factories import KnowledgeFactory
from apps.tools.factories import ToolFactory
from apps.workspaces.factories import UserFactory

pytestmark = pytest.mark.django_db


def _staff_user():
    return UserFactory(is_staff=True)


def _profile_data(profile, *, tools=(), knowledge=()):
    return {
        "credits": profile.credits,
        "credit_grant_per_period": profile.credit_grant_per_period,
        "run_count_limit": "",
        "run_count_period": "",
        "runs_used_in_period": profile.runs_used_in_period,
        "sandbox_time_seconds": "",
        "concurrency_max": "",
        "model_tier": profile.model_tier,
        "allowed_tools": [tool.pk for tool in tools],
        "allowed_knowledge": [kb.pk for kb in knowledge],
        "credit_refresh_schedule": profile.credit_refresh_schedule,
        "next_credit_refresh_at": "",
    }


def test_inline_form_rejects_cross_workspace_tool() -> None:
    end_user = EndUserFactory()
    tool = ToolFactory()
    form = ControlProfileInlineForm(
        data=_profile_data(end_user.profile, tools=[tool]),
        instance=end_user.profile,
    )

    assert not form.is_valid()
    assert form.errors["allowed_tools"] == [
        "Access assignments must belong to the end user's workspace."
    ]


def test_inline_form_rejects_cross_workspace_knowledge() -> None:
    end_user = EndUserFactory()
    kb = KnowledgeFactory()
    form = ControlProfileInlineForm(
        data=_profile_data(end_user.profile, knowledge=[kb]),
        instance=end_user.profile,
    )

    assert not form.is_valid()
    assert form.errors["allowed_knowledge"] == [
        "Access assignments must belong to the end user's workspace."
    ]


def test_inline_limits_tool_choices_to_end_user_workspace() -> None:
    end_user = EndUserFactory()
    tool = ToolFactory(workspace=end_user.workspace)
    other_tool = ToolFactory()
    request = RequestFactory().get(f"/admin/end_users/enduser/{end_user.pk}/change/")
    request.user = _staff_user()
    request.resolver_match = SimpleNamespace(kwargs={"object_id": str(end_user.pk)})
    inline = ControlProfileInline(EndUser, admin.site)
    field = ControlProfile._meta.get_field("allowed_tools")

    form_field = inline.formfield_for_manytomany(field, request)

    assert set(form_field.queryset) == {tool}
    assert other_tool not in form_field.queryset


def test_inline_limits_knowledge_choices_to_end_user_workspace() -> None:
    end_user = EndUserFactory()
    kb = KnowledgeFactory(workspace=end_user.workspace)
    other_kb = KnowledgeFactory()
    request = RequestFactory().get(f"/admin/end_users/enduser/{end_user.pk}/change/")
    request.user = _staff_user()
    request.resolver_match = SimpleNamespace(kwargs={"object_id": str(end_user.pk)})
    inline = ControlProfileInline(EndUser, admin.site)
    field = ControlProfile._meta.get_field("allowed_knowledge")

    form_field = inline.formfield_for_manytomany(field, request)

    assert set(form_field.queryset) == {kb}
    assert other_kb not in form_field.queryset
