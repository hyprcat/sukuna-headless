from __future__ import annotations

from typing import TYPE_CHECKING

from croniter import croniter  # type: ignore[import-untyped]
from django.core.exceptions import ValidationError

from apps.schedules.schemas import OutputRoute, ScheduleFormat

if TYPE_CHECKING:
    from apps.schedules.models.schedule import Schedule


def validate_schedule(schedule: Schedule, fmt: ScheduleFormat) -> None:
    _validate_cron(schedule, fmt)
    _validate_prompt(schedule, fmt)
    _validate_description(schedule, fmt)
    _validate_output_routing(schedule, fmt)
    _validate_same_workspace(schedule)


def _validate_cron(schedule: Schedule, fmt: ScheduleFormat) -> None:
    if len(schedule.cron_expression) > fmt.max_cron_expression_length:
        raise ValidationError(
            {"cron_expression": f"Exceeds {fmt.max_cron_expression_length} characters."}
        )
    if not croniter.is_valid(schedule.cron_expression):
        raise ValidationError({"cron_expression": "Invalid cron expression."})


def _validate_prompt(schedule: Schedule, fmt: ScheduleFormat) -> None:
    if len(schedule.prompt) > fmt.max_prompt_length:
        raise ValidationError({"prompt": f"Exceeds {fmt.max_prompt_length} characters."})


def _validate_description(schedule: Schedule, fmt: ScheduleFormat) -> None:
    if len(schedule.description) > fmt.max_description_length:
        raise ValidationError({"description": f"Exceeds {fmt.max_description_length} characters."})


def _validate_output_routing(schedule: Schedule, fmt: ScheduleFormat) -> None:
    if not isinstance(schedule.output_routing, list):
        raise ValidationError({"output_routing": "Must be a JSON array."})
    if len(schedule.output_routing) > fmt.max_output_routes:
        raise ValidationError({"output_routing": f"Maximum {fmt.max_output_routes} output routes."})
    for i, entry in enumerate(schedule.output_routing):
        try:
            OutputRoute.model_validate(entry)
        except Exception:
            raise ValidationError(
                {"output_routing": f"Invalid output route at index {i}."}
            ) from None


def _validate_same_workspace(schedule: Schedule) -> None:
    if hasattr(schedule, "agent") and schedule.agent_id:
        _validate_agent_workspace(schedule)
    if hasattr(schedule, "target_end_user") and schedule.target_end_user_id:
        _validate_end_user_workspace(schedule)


def _validate_agent_workspace(schedule: Schedule) -> None:
    from apps.agents.models import Agent  # noqa: PLC0415

    agent_ws = (
        Agent.objects.filter(pk=schedule.agent_id).values_list("workspace_id", flat=True).first()
    )
    if agent_ws and agent_ws != schedule.workspace_id:
        raise ValidationError({"agent": "Agent must belong to the same workspace."})


def _validate_end_user_workspace(schedule: Schedule) -> None:
    from apps.end_users.models import EndUser  # noqa: PLC0415

    eu_ws = (
        EndUser.objects.filter(pk=schedule.target_end_user_id)
        .values_list("workspace_id", flat=True)
        .first()
    )
    if eu_ws and eu_ws != schedule.workspace_id:
        raise ValidationError({"target_end_user": "End user must belong to the same workspace."})
