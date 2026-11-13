from __future__ import annotations

import strawberry
import strawberry_django
from strawberry import relay
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.agents.api.types import AgentType
from apps.agents.models import Agent
from apps.core.decorators import requires_role, requires_scope, workspace_scoped


def _agent_pk(id: strawberry.ID) -> int | None:
    raw = str(id)
    try:
        global_id = relay.GlobalID.from_id(raw)
    except ValueError:
        return int(raw) if raw.isdecimal() else None
    if global_id.type_name != "AgentType":
        return None
    return int(global_id.node_id) if global_id.node_id.isdecimal() else None


@strawberry.type
class AgentQuery:
    @strawberry_django.connection(DjangoListConnection[AgentType])
    @workspace_scoped
    @requires_role(Action.AGENTS_READ)
    @requires_scope("agents:read")
    def agents(
        self,
        info: Info,
        is_active: bool | None = None,
    ) -> list[Agent]:
        return Agent.objects.for_workspace(info.context.workspace.pk, is_active=is_active)  # type: ignore[return-value]

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.AGENTS_READ)
    @requires_scope("agents:read")
    def agent(self, info: Info, id: strawberry.ID) -> AgentType | None:
        pk = _agent_pk(id)
        if pk is None:
            return None
        return Agent.objects.get_for_workspace(info.context.workspace.pk, pk)  # type: ignore[return-value]
