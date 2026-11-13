from __future__ import annotations

from datetime import timedelta

import factory
from django.utils import timezone

from apps.agents.factories import AgentFactory
from apps.end_users.factories import EndUserFactory
from apps.schedules.models import FailureHandling, Schedule, ScheduleStatus
from apps.schedules.models.execution import ExecutionOutcome, ScheduleExecution
from apps.workspaces.factories import WorkspaceFactory


class ScheduleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Schedule

    workspace = factory.SubFactory(WorkspaceFactory)
    agent = factory.SubFactory(AgentFactory, workspace=factory.SelfAttribute("..workspace"))
    target_end_user = factory.SubFactory(
        EndUserFactory, workspace=factory.SelfAttribute("..workspace")
    )
    name = factory.Sequence(lambda n: f"schedule-{n}")
    prompt = factory.Faker("sentence")
    cron_expression = "0 9 * * *"
    failure_handling = FailureHandling.SKIP
    status = ScheduleStatus.ACTIVE
    next_run_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))

    class Params:
        paused = factory.Trait(
            status=ScheduleStatus.PAUSED,
            paused_at=factory.LazyFunction(timezone.now),
            next_run_at=None,
        )
        disabled = factory.Trait(
            status=ScheduleStatus.DISABLED,
            disabled_at=factory.LazyFunction(timezone.now),
            next_run_at=None,
        )
        due_now = factory.Trait(
            next_run_at=factory.LazyFunction(lambda: timezone.now() - timedelta(minutes=1)),
        )


class ScheduleExecutionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ScheduleExecution

    schedule = factory.SubFactory(ScheduleFactory)
    outcome = ExecutionOutcome.SUCCESS
    scheduled_for = factory.LazyFunction(timezone.now)
