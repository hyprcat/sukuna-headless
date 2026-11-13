from __future__ import annotations

from types import SimpleNamespace

import pytest
import strawberry
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.end_users.api.mutations import EndUserMutation
from apps.end_users.factories import EndUserFactory
from apps.knowledge.factories import KnowledgeFactory
from apps.tools.factories import ToolFactory
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q:
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class _M(EndUserMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M, extensions=[DjangoOptimizerExtension])


def _ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: True)
    principal = SimpleNamespace(workspace_id=workspace.pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=workspace, principal=principal)


UPDATE_END_USER = """
mutation($id: ID!, $input: UpdateEndUserInput!) {
    updateEndUser(id: $id, input: $input) {
        success
        errors { code field message }
        endUser { displayName }
    }
}
"""


def test_update_end_user_accepts_relay_global_id() -> None:
    end_user = EndUserFactory()

    result = _schema.execute_sync(
        UPDATE_END_USER,
        variable_values={
            "id": relay.to_base64("EndUserType", end_user.pk),
            "input": {"displayName": "Ada"},
        },
        context_value=_ctx(end_user.workspace),
    )

    assert result.errors is None
    assert result.data["updateEndUser"]["success"] is True
    assert result.data["updateEndUser"]["endUser"]["displayName"] == "Ada"


UPDATE_CONTROLS = """
mutation($input: UpdateEndUserControlsInput!) {
    updateEndUserControls(input: $input) {
        success
        errors { code field message }
        endUser { externalUserId }
    }
}
"""


def test_update_controls_uses_single_input_contract() -> None:
    sdl = str(_schema)

    assert "updateEndUserControls(input: UpdateEndUserControlsInput!)" in sdl
    assert "updateEndUserControls(id:" not in sdl
    assert "id: ID!" in sdl


def test_update_controls_updates_scalars_and_allowed_access() -> None:
    workspace = WorkspaceFactory()
    end_user = EndUserFactory(workspace=workspace)
    tool = ToolFactory(workspace=workspace)
    kb = KnowledgeFactory(workspace=workspace)

    result = _schema.execute_sync(
        UPDATE_CONTROLS,
        variable_values={
            "input": {
                "id": relay.to_base64("EndUserType", end_user.pk),
                "credits": 25,
                "runCountLimit": 5,
                "runCountPeriod": "day",
                "modelTier": "pro",
                "allowedToolIds": [relay.to_base64("ToolType", tool.pk)],
                "allowedKnowledgeIds": [relay.to_base64("KnowledgeType", kb.pk)],
            },
        },
        context_value=_ctx(workspace),
    )

    assert result.errors is None
    assert result.data["updateEndUserControls"]["success"] is True
    end_user.profile.refresh_from_db()
    assert end_user.profile.credits == 25
    assert end_user.profile.model_tier == "pro"
    assert list(end_user.profile.allowed_tools.all()) == [tool]
    assert list(end_user.profile.allowed_knowledge.all()) == [kb]


def test_update_controls_sets_next_refresh_when_schedule_enabled() -> None:
    end_user = EndUserFactory()

    result = _schema.execute_sync(
        UPDATE_CONTROLS,
        variable_values={
            "input": {
                "id": relay.to_base64("EndUserType", end_user.pk),
                "creditRefreshSchedule": "daily",
            },
        },
        context_value=_ctx(end_user.workspace),
    )

    assert result.errors is None
    assert result.data["updateEndUserControls"]["success"] is True
    end_user.profile.refresh_from_db()
    assert end_user.profile.next_credit_refresh_at is not None


def test_update_controls_clears_next_refresh_when_schedule_disabled() -> None:
    end_user = EndUserFactory(profile__credit_refresh_schedule="daily")
    end_user.profile.update_controls(
        workspace_id=end_user.workspace_id, credit_refresh_schedule="daily"
    )

    result = _schema.execute_sync(
        UPDATE_CONTROLS,
        variable_values={
            "input": {
                "id": relay.to_base64("EndUserType", end_user.pk),
                "creditRefreshSchedule": "never",
            },
        },
        context_value=_ctx(end_user.workspace),
    )

    assert result.errors is None
    assert result.data["updateEndUserControls"]["success"] is True
    end_user.profile.refresh_from_db()
    assert end_user.profile.next_credit_refresh_at is None


def test_update_controls_rejects_cross_workspace_allowed_tool() -> None:
    workspace = WorkspaceFactory()
    end_user = EndUserFactory(workspace=workspace)
    other_tool = ToolFactory()

    result = _schema.execute_sync(
        UPDATE_CONTROLS,
        variable_values={
            "input": {
                "id": relay.to_base64("EndUserType", end_user.pk),
                "allowedToolIds": [relay.to_base64("ToolType", other_tool.pk)],
            },
        },
        context_value=_ctx(workspace),
    )

    assert result.errors is None
    data = result.data["updateEndUserControls"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "NOT_FOUND"
    assert end_user.profile.allowed_tools.count() == 0
