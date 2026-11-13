from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    from datetime import datetime

    from apps.schedules.models.schedule import Schedule
else:
    Schedule = models.Model


class FailureHandling(models.TextChoices):
    RETRY = "retry"
    SKIP = "skip"
    ALERT = "alert"
    LOG_SILENT = "log_silent"


class ScheduleStatus(models.TextChoices):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class ScheduleQuerySet(models.QuerySet[Schedule]):
    def for_workspace(self, workspace_id: int) -> ScheduleQuerySet:
        return self.filter(workspace_id=workspace_id)

    def active(self) -> ScheduleQuerySet:
        return self.filter(status=ScheduleStatus.ACTIVE)

    def due(self, now: datetime | None = None) -> ScheduleQuerySet:
        now = now or timezone.now()
        return self.active().filter(next_run_at__lte=now).order_by("next_run_at", "pk")
