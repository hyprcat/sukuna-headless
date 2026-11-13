from __future__ import annotations

from typing import Any, cast

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, workspace_scoped
from apps.schedules.api.types import (
    CreateSchedulePayload,
    DisableSchedulePayload,
    PauseSchedulePayload,
    ResumeSchedulePayload,
    UpdateSchedulePayload,
)
from apps.schedules.models import Schedule


def _get_schedule(workspace_pk: int, schedule_id: str) -> Schedule:
    pk = parse_int_id(schedule_id, expected_type="ScheduleType")
    return Schedule.get_for_workspace_or_raise(workspace_pk, pk)


def _collect_updates(inp: UpdateScheduleInput) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for field in ("name", "description", "prompt", "cron_expression", "failure_handling"):
        value = getattr(inp, field)
        if value is not None:
            updates[field] = value
    if inp.output_routing is not strawberry.UNSET:
        updates["output_routing"] = cast("list[Any]", inp.output_routing or [])
    _add_schedule_link_updates(updates, inp)
    return updates


def _add_schedule_link_updates(updates: dict[str, Any], inp: UpdateScheduleInput) -> None:
    if inp.agent_id is not None:
        updates["agent_id"] = parse_int_id(
            inp.agent_id,
            expected_type="AgentType",
            field="agent_id",
        )
    if inp.target_end_user_id is not None:
        updates["target_end_user_id"] = parse_int_id(
            inp.target_end_user_id,
            expected_type="EndUserType",
            field="target_end_user_id",
        )


@strawberry.input
class CreateScheduleInput:
    name: str
    agent_id: strawberry.ID
    target_end_user_id: strawberry.ID
    prompt: str
    cron_expression: str
    description: str = ""
    failure_handling: str = "skip"
    output_routing: strawberry.scalars.JSON | None = strawberry.UNSET


@strawberry.input
class UpdateScheduleInput:
    name: str | None = None
    description: str | None = None
    prompt: str | None = None
    cron_expression: str | None = None
    failure_handling: str | None = None
    output_routing: strawberry.scalars.JSON | None = strawberry.UNSET
    agent_id: strawberry.ID | None = None
    target_end_user_id: strawberry.ID | None = None


@strawberry.type
class ScheduleMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.SCHEDULES_WRITE)
    @catch_domain_errors(CreateSchedulePayload)
    def create_schedule(self, info: Info, input: CreateScheduleInput) -> CreateSchedulePayload:
        has_routing = input.output_routing is not strawberry.UNSET
        routing = cast("list[Any]", input.output_routing or []) if has_routing else []
        agent_pk = parse_int_id(input.agent_id, expected_type="AgentType", field="agent_id")
        eu_pk = parse_int_id(
            input.target_end_user_id, expected_type="EndUserType", field="target_end_user_id"
        )
        schedule = Schedule.create_for_workspace(
            info.context.workspace.pk,
            name=input.name,
            agent_id=agent_pk,
            target_end_user_id=eu_pk,
            prompt=input.prompt,
            cron_expression=input.cron_expression,
            description=input.description,
            failure_handling=input.failure_handling,
            output_routing=routing,
        )
        return CreateSchedulePayload(success=True, errors=[], schedule=schedule)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.SCHEDULES_WRITE)
    @catch_domain_errors(UpdateSchedulePayload)
    def update_schedule(
        self,
        info: Info,
        id: strawberry.ID,
        input: UpdateScheduleInput,
    ) -> UpdateSchedulePayload:
        schedule = _get_schedule(info.context.workspace.pk, id)
        schedule.update_fields_from(_collect_updates(input))
        return UpdateSchedulePayload(success=True, errors=[], schedule=schedule)  # type: ignore[arg-type]

    @strawberry.mutation
    @catch_domain_errors(PauseSchedulePayload)
    @workspace_scoped
    @requires_role(Action.SCHEDULES_PAUSE)
    def pause_schedule(self, info: Info, id: strawberry.ID) -> PauseSchedulePayload:
        schedule = _get_schedule(info.context.workspace.pk, id)
        schedule.pause()
        return PauseSchedulePayload(success=True, errors=[], schedule=schedule)  # type: ignore[arg-type]

    @strawberry.mutation
    @catch_domain_errors(ResumeSchedulePayload)
    @workspace_scoped
    @requires_role(Action.SCHEDULES_PAUSE)
    def resume_schedule(self, info: Info, id: strawberry.ID) -> ResumeSchedulePayload:
        schedule = _get_schedule(info.context.workspace.pk, id)
        schedule.resume()
        return ResumeSchedulePayload(success=True, errors=[], schedule=schedule)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.SCHEDULES_DELETE)
    @catch_domain_errors(DisableSchedulePayload)
    def disable_schedule(self, info: Info, id: strawberry.ID) -> DisableSchedulePayload:
        schedule = _get_schedule(info.context.workspace.pk, id)
        schedule.disable()
        return DisableSchedulePayload(success=True, errors=[], schedule=schedule)  # type: ignore[arg-type]
