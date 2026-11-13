from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from apps.agents.schemas import AgentFormat
from apps.policies.models import Policy

if TYPE_CHECKING:
    from apps.agents.models.agent import Agent


def validate_agent(agent: Agent, fmt: AgentFormat) -> None:
    _validate_description(agent, fmt)
    _validate_system_prompt(agent, fmt)
    _validate_policy_workspace(agent)


def _validate_description(agent: Agent, fmt: AgentFormat) -> None:
    if len(agent.description) > fmt.max_description_length:
        raise ValidationError({"description": f"Exceeds {fmt.max_description_length} characters."})


def _validate_system_prompt(agent: Agent, fmt: AgentFormat) -> None:
    if len(agent.system_prompt) > fmt.max_system_prompt_length:
        raise ValidationError(
            {"system_prompt": f"Exceeds {fmt.max_system_prompt_length} characters."}
        )


def _validate_policy_workspace(agent: Agent) -> None:
    if agent.policy_override_id is None:
        return
    policy_ws = (
        Policy.objects.filter(pk=agent.policy_override_id)
        .values_list("workspace_id", flat=True)
        .first()
    )
    if policy_ws != agent.workspace_id:
        raise ValidationError({"policy_override": "Policy must belong to the same workspace."})
