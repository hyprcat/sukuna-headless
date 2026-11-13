from __future__ import annotations

from typing import Any, cast

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id, parse_int_ids
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.end_users.api.types import (
    ActivateEndUserPayload,
    CreateEndUserPayload,
    DeactivateEndUserPayload,
    UpdateEndUserControlsPayload,
    UpdateEndUserPayload,
)
from apps.end_users.models import EndUser


def _get_end_user(workspace_pk: int, end_user_id: str) -> EndUser:
    pk = parse_int_id(end_user_id, expected_type="EndUserType")
    return EndUser.get_for_workspace_or_raise(workspace_pk, pk)


@strawberry.input
class CreateEndUserInput:
    external_user_id: str
    display_name: str = ""
    tier_label: str = ""
    metadata: strawberry.scalars.JSON = strawberry.UNSET


@strawberry.input
class UpdateEndUserInput:
    display_name: str | None = strawberry.UNSET
    tier_label: str | None = strawberry.UNSET
    metadata: strawberry.scalars.JSON | None = strawberry.UNSET


@strawberry.input
class UpdateEndUserControlsInput:
    id: strawberry.ID
    credits: int | None = strawberry.UNSET
    credit_grant_per_period: int | None = strawberry.UNSET
    run_count_limit: int | None = strawberry.UNSET
    run_count_period: str | None = strawberry.UNSET
    sandbox_time_seconds: int | None = strawberry.UNSET
    concurrency_max: int | None = strawberry.UNSET
    model_tier: str | None = strawberry.UNSET
    credit_refresh_schedule: str | None = strawberry.UNSET
    allowed_tool_ids: list[strawberry.ID] | None = strawberry.UNSET
    allowed_knowledge_ids: list[strawberry.ID] | None = strawberry.UNSET


@strawberry.type
class EndUserMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.END_USERS_DELETE)
    @requires_scope("end_users:write")
    @catch_domain_errors(DeactivateEndUserPayload)
    def deactivate_end_user(self, info: Info, id: strawberry.ID) -> DeactivateEndUserPayload:
        eu = _get_end_user(info.context.workspace.pk, id)
        eu.deactivate()
        return DeactivateEndUserPayload(
            success=True,
            errors=[],
            end_user=eu,  # type: ignore[arg-type]
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.END_USERS_WRITE)
    @requires_scope("end_users:write")
    @catch_domain_errors(ActivateEndUserPayload)
    def activate_end_user(self, info: Info, id: strawberry.ID) -> ActivateEndUserPayload:
        eu = _get_end_user(info.context.workspace.pk, id)
        eu.activate()
        return ActivateEndUserPayload(
            success=True,
            errors=[],
            end_user=eu,  # type: ignore[arg-type]
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.END_USERS_WRITE)
    @requires_scope("end_users:write")
    @catch_domain_errors(CreateEndUserPayload)
    def create_end_user(self, info: Info, input: CreateEndUserInput) -> CreateEndUserPayload:
        meta: dict[str, Any] = {}
        if input.metadata is not strawberry.UNSET:
            meta = cast("dict[str, Any]", input.metadata)
        eu = EndUser.create_with_profile(
            info.context.workspace.pk,
            external_user_id=input.external_user_id,
            display_name=input.display_name,
            tier_label=input.tier_label,
            metadata=meta,
        )
        return CreateEndUserPayload(success=True, errors=[], end_user=eu)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.END_USERS_WRITE)
    @requires_scope("end_users:write")
    @catch_domain_errors(UpdateEndUserPayload)
    def update_end_user(
        self, info: Info, id: strawberry.ID, input: UpdateEndUserInput
    ) -> UpdateEndUserPayload:
        eu = _get_end_user(info.context.workspace.pk, id)
        kwargs = _collect_unset(input, ("display_name", "tier_label", "metadata"))
        eu.update(**kwargs)
        return UpdateEndUserPayload(success=True, errors=[], end_user=eu)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.END_USERS_WRITE)
    @requires_scope("end_users:write")
    @catch_domain_errors(UpdateEndUserControlsPayload)
    def update_end_user_controls(
        self, info: Info, input: UpdateEndUserControlsInput
    ) -> UpdateEndUserControlsPayload:
        eu = _get_end_user(info.context.workspace.pk, input.id)
        fields = _control_ids(_collect_controls(input))
        eu.profile.update_controls(workspace_id=info.context.workspace.pk, **fields)
        return UpdateEndUserControlsPayload(
            success=True,
            errors=[],
            end_user=eu,  # type: ignore[arg-type]
        )


def _collect_unset(input: Any, names: tuple[str, ...]) -> dict[str, Any]:
    """Return a dict of only the fields that were explicitly provided."""
    result: dict[str, Any] = {}
    for name in names:
        value = getattr(input, name)
        if value is not strawberry.UNSET:
            result[name] = value if value is not None else ("" if name != "metadata" else {})
    return result


def _collect_controls(input: UpdateEndUserControlsInput) -> dict[str, Any]:
    """Extract provided control fields, mapping UNSET to omission."""
    fields: dict[str, Any] = {}
    for name in (
        "credits",
        "credit_grant_per_period",
        "run_count_limit",
        "run_count_period",
        "sandbox_time_seconds",
        "concurrency_max",
        "model_tier",
        "credit_refresh_schedule",
        "allowed_tool_ids",
        "allowed_knowledge_ids",
    ):
        value = getattr(input, name)
        if value is not strawberry.UNSET:
            fields[name] = value
    return fields


def _control_ids(fields: dict[str, Any]) -> dict[str, Any]:
    if "allowed_tool_ids" in fields:
        fields["allowed_tool_ids"] = parse_int_ids(
            fields["allowed_tool_ids"],
            expected_type="ToolType",
            field="allowed_tool_ids",
        )
    if "allowed_knowledge_ids" in fields:
        fields["allowed_knowledge_ids"] = parse_int_ids(
            fields["allowed_knowledge_ids"],
            expected_type="KnowledgeType",
            field="allowed_knowledge_ids",
        )
    return fields
