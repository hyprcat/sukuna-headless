from __future__ import annotations

import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.decorators import requires_role, workspace_scoped
from apps.policies.api.types import PolicyType
from apps.policies.models import Policy


@strawberry.type
class PolicyQuery:
    @strawberry_django.connection(DjangoListConnection[PolicyType])
    @workspace_scoped
    @requires_role(Action.POLICIES_READ)
    def policies(self, info: Info) -> list[Policy]:
        return Policy.for_workspace(info.context.workspace.pk)  # type: ignore[return-value]

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.POLICIES_READ)
    def policy(self, info: Info, id: strawberry.ID) -> PolicyType | None:
        pk = parse_int_id(id, expected_type="PolicyType")
        return Policy.get_for_workspace(info.context.workspace.pk, pk)  # type: ignore[return-value]
