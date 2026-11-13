from __future__ import annotations

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, workspace_scoped
from apps.policies.api.types import CreatePolicyPayload, UpdatePolicyPayload
from apps.policies.models import Policy


def _get_policy(workspace_pk: int, policy_id: str) -> Policy:
    pk = parse_int_id(policy_id, expected_type="PolicyType")
    return Policy.get_for_workspace_or_raise(workspace_pk, pk)


@strawberry.input
class CreatePolicyInput:
    name: str
    action_restrictions: list[str] | None = strawberry.UNSET
    domain_restrictions: list[str] | None = strawberry.UNSET
    output_restrictions: list[str] | None = strawberry.UNSET


@strawberry.input
class UpdatePolicyInput:
    name: str | None = strawberry.UNSET
    action_restrictions: list[str] | None = strawberry.UNSET
    domain_restrictions: list[str] | None = strawberry.UNSET
    output_restrictions: list[str] | None = strawberry.UNSET


@strawberry.type
class PolicyMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.POLICIES_WRITE)
    @catch_domain_errors(CreatePolicyPayload)
    def create_policy(self, info: Info, input: CreatePolicyInput) -> CreatePolicyPayload:
        policy = Policy.create_for_workspace(
            info.context.workspace.pk,
            name=input.name,
            action_restrictions=input.action_restrictions
            if input.action_restrictions is not strawberry.UNSET
            else None,
            domain_restrictions=input.domain_restrictions
            if input.domain_restrictions is not strawberry.UNSET
            else None,
            output_restrictions=input.output_restrictions
            if input.output_restrictions is not strawberry.UNSET
            else None,
        )
        return CreatePolicyPayload(success=True, errors=[], policy=policy)  # type: ignore[arg-type]

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.POLICIES_WRITE)
    @catch_domain_errors(UpdatePolicyPayload)
    def update_policy(
        self, info: Info, id: strawberry.ID, input: UpdatePolicyInput
    ) -> UpdatePolicyPayload:
        policy = _get_policy(info.context.workspace.pk, id)
        fields = ("name", "action_restrictions", "domain_restrictions", "output_restrictions")
        provided = {
            k: getattr(input, k) for k in fields if getattr(input, k) is not strawberry.UNSET
        }
        policy.update(**provided)
        return UpdatePolicyPayload(success=True, errors=[], policy=policy)  # type: ignore[arg-type]
