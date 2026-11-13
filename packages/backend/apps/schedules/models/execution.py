from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.db import models

from apps.core.exceptions import Conflict

if TYPE_CHECKING:
    from django.db.models import QuerySet
from apps.core.models import TimestampedModel


class ExecutionOutcome(models.TextChoices):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScheduleExecutionQuerySet(models.QuerySet["ScheduleExecution"]):
    def update(self, **kwargs: Any) -> int:
        raise Conflict("ScheduleExecution is append-only.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise Conflict("ScheduleExecution is append-only.")


class ScheduleExecution(TimestampedModel):
    schedule = models.ForeignKey(
        "schedules.Schedule",
        on_delete=models.CASCADE,
        related_name="executions",
    )
    run = models.ForeignKey(
        "runs.Run",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="schedule_executions",
    )
    outcome = models.CharField(max_length=12, choices=ExecutionOutcome)
    scheduled_for = models.DateTimeField(
        help_text="The fire time this execution corresponds to.",
    )
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    skip_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Populated when outcome is skipped (e.g. end user over quota).",
    )
    error_message = models.TextField(blank=True, default="")
    objects = ScheduleExecutionQuerySet.as_manager()

    class Meta:
        db_table = "schedules_execution"
        ordering = ("-scheduled_for",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("schedule", "-scheduled_for")),
            models.Index(fields=("outcome",)),
        ]

    def __str__(self) -> str:
        return f"Execution[{self.schedule_id}@{self.scheduled_for}] → {self.outcome}"

    @classmethod
    def for_schedule_in_workspace(
        cls,
        schedule_id: object,
        workspace_id: int,
    ) -> QuerySet[ScheduleExecution]:
        return cls.objects.filter(schedule_id=schedule_id, schedule__workspace_id=workspace_id)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise Conflict("ScheduleExecution is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise Conflict("ScheduleExecution is append-only.")
