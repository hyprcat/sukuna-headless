from __future__ import annotations

from types import SimpleNamespace

import pytest
import strawberry
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.agents.factories import AgentFactory
from apps.end_users.factories import EndUserFactory
from apps.schedules.api.mutations import ScheduleMutation
from apps.schedules.factories import ScheduleFactory
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q:
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class _M(ScheduleMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M, extensions=[DjangoOptimizerExtension])


def _ctx(workspace: object, *, can_act: bool = True) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: can_act)
    principal = SimpleNamespace(workspace_id=workspace.pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=workspace, principal=principal)


def _gid(type_name: str, pk: object) -> str:
    return relay.to_base64(type_name, pk)


CREATE_SCHEDULE = """
mutation($input: CreateScheduleInput!) {
    createSchedule(input: $input) {
        success
        errors { code field message }
        schedule { name agentName targetEndUserExternalId }
    }
}
"""


def test_create_schedule_accepts_relay_global_ids() -> None:
    workspace = WorkspaceFactory()
    agent = AgentFactory(workspace=workspace)
    end_user = EndUserFactory(workspace=workspace, external_user_id="user-1")

    result = _schema.execute_sync(
        CREATE_SCHEDULE,
        variable_values={
            "input": {
                "name": "Digest",
                "agentId": relay.to_base64("AgentType", agent.pk),
                "targetEndUserId": relay.to_base64("EndUserType", end_user.pk),
                "prompt": "Summarize the week",
                "cronExpression": "0 9 * * 1",
            }
        },
        context_value=_ctx(workspace),
    )

    assert result.errors is None
    data = result.data["createSchedule"]
    assert data["success"] is True
    assert data["schedule"]["agentName"] == agent.name
    assert data["schedule"]["targetEndUserExternalId"] == "user-1"


UPDATE_SCHEDULE = """
mutation($id: ID!, $input: UpdateScheduleInput!) {
    updateSchedule(id: $id, input: $input) {
        success
        errors { code field message }
        schedule { name }
    }
}
"""


def test_update_schedule_rejects_wrong_relay_id_type() -> None:
    schedule = ScheduleFactory()

    result = _schema.execute_sync(
        UPDATE_SCHEDULE,
        variable_values={
            "id": _gid("ScheduleType", schedule.pk),
            "input": {"agentId": _gid("ToolType", 1)},
        },
        context_value=_ctx(schedule.workspace),
    )

    assert result.errors is None
    data = result.data["updateSchedule"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "agent_id"


PAUSE_SCHEDULE = """
mutation($id: ID!) {
    pauseSchedule(id: $id) {
        success
        errors { code field message }
        schedule { status nextRunAt }
    }
}
"""


RESUME_SCHEDULE = """
mutation($id: ID!) {
    resumeSchedule(id: $id) {
        success
        errors { code field message }
        schedule { status nextRunAt }
    }
}
"""


def test_pause_and_resume_schedule_accept_relay_global_ids() -> None:
    schedule = ScheduleFactory()

    pause = _schema.execute_sync(
        PAUSE_SCHEDULE,
        variable_values={"id": _gid("ScheduleType", schedule.pk)},
        context_value=_ctx(schedule.workspace),
    )
    assert pause.errors is None
    assert pause.data["pauseSchedule"]["success"] is True
    assert pause.data["pauseSchedule"]["schedule"]["status"] == "PAUSED"
    assert pause.data["pauseSchedule"]["schedule"]["nextRunAt"] is None

    resume = _schema.execute_sync(
        RESUME_SCHEDULE,
        variable_values={"id": _gid("ScheduleType", schedule.pk)},
        context_value=_ctx(schedule.workspace),
    )
    assert resume.errors is None
    assert resume.data["resumeSchedule"]["success"] is True
    assert resume.data["resumeSchedule"]["schedule"]["status"] == "ACTIVE"
    assert resume.data["resumeSchedule"]["schedule"]["nextRunAt"] is not None


def test_pause_schedule_rejects_wrong_relay_id_type() -> None:
    schedule = ScheduleFactory()

    result = _schema.execute_sync(
        PAUSE_SCHEDULE,
        variable_values={"id": _gid("ToolType", schedule.pk)},
        context_value=_ctx(schedule.workspace),
    )

    assert result.errors is None
    data = result.data["pauseSchedule"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "id"


def test_resume_disabled_schedule_returns_payload_error() -> None:
    schedule = ScheduleFactory(disabled=True)

    result = _schema.execute_sync(
        RESUME_SCHEDULE,
        variable_values={"id": _gid("ScheduleType", schedule.pk)},
        context_value=_ctx(schedule.workspace),
    )

    assert result.errors is None
    data = result.data["resumeSchedule"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


def test_pause_schedule_permission_error_uses_payload() -> None:
    schedule = ScheduleFactory()

    result = _schema.execute_sync(
        PAUSE_SCHEDULE,
        variable_values={"id": _gid("ScheduleType", schedule.pk)},
        context_value=_ctx(schedule.workspace, can_act=False),
    )

    assert result.errors is None
    data = result.data["pauseSchedule"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "PERMISSION_DENIED"
