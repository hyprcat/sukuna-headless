from __future__ import annotations

import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.core.decorators import requires_role, workspace_scoped
from apps.schedules.api.types import ScheduleExecutionType, ScheduleType
from apps.schedules.models import Schedule, ScheduleExecution


@strawberry.type
class ScheduleQuery:
    @strawberry_django.connection(DjangoListConnection[ScheduleType])
    @workspace_scoped
    @requires_role(Action.SCHEDULES_READ)
    def schedules(
        self,
        info: Info,
        status: str | None = None,
        agent_id: int | None = None,
    ) -> list[Schedule]:
        return Schedule.for_workspace(  # type: ignore[return-value]
            info.context.workspace.pk,
            status=status,
            agent_id=agent_id,
        )

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.SCHEDULES_READ)
    def schedule(self, info: Info, id: strawberry.ID) -> ScheduleType | None:
        return Schedule.get_for_workspace(info.context.workspace.pk, id)  # type: ignore[return-value]

    @strawberry_django.connection(DjangoListConnection[ScheduleExecutionType])
    @workspace_scoped
    @requires_role(Action.SCHEDULES_READ)
    def schedule_executions(
        self,
        info: Info,
        schedule_id: strawberry.ID,
    ) -> list[ScheduleExecution]:
        return ScheduleExecution.for_schedule_in_workspace(  # type: ignore[return-value]
            schedule_id,
            info.context.workspace.pk,
        )
