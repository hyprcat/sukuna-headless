from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, cast

from croniter import croniter  # type: ignore[import-untyped]  # croniter ships no stubs.
from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import Action
from apps.core.events import record_event
from apps.core.exceptions import Conflict, NotFound
from apps.core.models import TimestampedModel
from apps.schedules.models.queryset import FailureHandling, ScheduleQuerySet, ScheduleStatus
from apps.schedules.models.validators import validate_schedule
from apps.schedules.schemas import OutputRoute, ScheduleFormat

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.workspaces.models.member import WorkspaceMember


class Schedule(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    agent = models.ForeignKey(
        "agents.Agent",
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    target_end_user = models.ForeignKey(
        "end_users.EndUser",
        on_delete=models.CASCADE,
        related_name="schedules",
        help_text="End user whose controls are checked and debited on each tick.",
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    prompt = models.TextField(
        max_length=64_000,
        help_text="Prompt passed to the agent on each scheduled run.",
    )
    cron_expression = models.CharField(
        max_length=120,
        help_text="Standard 5-field cron expression (minute hour dom month dow).",
    )
    failure_handling = models.CharField(
        max_length=16,
        choices=FailureHandling,
        default=FailureHandling.SKIP,
    )
    output_routing = models.JSONField(
        default=list,
        blank=True,
        help_text="List of OutputRoute objects describing where run output goes.",
    )
    status = models.CharField(
        max_length=12,
        choices=ScheduleStatus,
        default=ScheduleStatus.ACTIVE,
        db_index=True,
    )
    next_run_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
        help_text="Precomputed next fire time; updated after every execution or resume.",
    )
    last_run_at = models.DateTimeField(blank=True, null=True)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    paused_at = models.DateTimeField(blank=True, null=True)
    disabled_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()
    objects = ScheduleQuerySet.as_manager()

    class Meta:
        db_table = "schedules_schedule"
        ordering = ("name",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("workspace", "name"),
                name="schedules_workspace_name_uniq",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "status")),
            models.Index(fields=("agent",)),
            models.Index(fields=("target_end_user",)),
            models.Index(fields=("status", "next_run_at")),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        validate_schedule(self, ScheduleFormat())

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        if self._should_compute_next_run():
            self.next_run_at = self._compute_next_run()
            self._include_update_field(kwargs, "next_run_at")
        super().save(*args, **kwargs)

    def pause(self) -> None:
        schedule = self._pause_locked()
        if schedule is None:
            return
        schedule._emit_event("schedule_paused")

    def resume(self) -> None:
        schedule = self._resume_locked()
        if schedule is None:
            return
        schedule._emit_event("schedule_resumed")

    def disable(self) -> None:
        if self.status == ScheduleStatus.DISABLED:
            return
        self.status = ScheduleStatus.DISABLED
        self.disabled_at = timezone.now()
        self.next_run_at = None
        self.save(update_fields=("status", "disabled_at", "next_run_at", "updated_at"))
        self._emit_event("schedule_disabled")

    def record_success(self) -> None:
        now = timezone.now()
        self.last_run_at = now
        self.consecutive_failures = 0
        self.next_run_at = self._compute_next_run(after=now)
        self.save(
            update_fields=("last_run_at", "consecutive_failures", "next_run_at", "updated_at")
        )

    def record_failure(self) -> None:
        now = timezone.now()
        fmt = ScheduleFormat()
        self.last_run_at = now
        self.consecutive_failures += 1
        if self.consecutive_failures >= fmt.max_retry_attempts:
            self.save(update_fields=("last_run_at", "consecutive_failures", "updated_at"))
            self.disable()
            return
        self.next_run_at = self._compute_next_run(after=now)
        self.save(
            update_fields=("last_run_at", "consecutive_failures", "next_run_at", "updated_at")
        )

    def advance_next_run(self) -> None:
        self.next_run_at = self._compute_next_run()
        self.save(update_fields=("next_run_at", "updated_at"))

    def parsed_output_routes(self) -> list[OutputRoute]:
        """Validated output routes; consumed by post-run output delivery."""
        return [OutputRoute.model_validate(entry) for entry in self.output_routing]

    def can_be_edited_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.SCHEDULES_WRITE)

    def can_be_deleted_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.SCHEDULES_DELETE)

    @classmethod
    def for_workspace(
        cls,
        workspace_id: int,
        *,
        status: str | None = None,
        agent_id: int | None = None,
    ) -> QuerySet[Schedule]:
        qs = cls.objects.for_workspace(workspace_id).select_related("agent", "target_end_user")
        if status is not None:
            qs = qs.filter(status=status)
        if agent_id is not None:
            qs = qs.filter(agent_id=agent_id)
        return qs

    @classmethod
    def get_for_workspace(cls, workspace_id: int, pk: object) -> Schedule | None:
        return (
            cls.objects.filter(pk=pk, workspace_id=workspace_id)
            .select_related("agent", "target_end_user")
            .first()
        )

    @classmethod
    def get_for_workspace_or_raise(cls, workspace_id: int, pk: object) -> Schedule:
        try:
            return cls.objects.get(pk=pk, workspace_id=workspace_id)
        except cls.DoesNotExist as exc:
            raise NotFound("Schedule not found.") from exc

    @classmethod
    def create_for_workspace(cls, workspace_id: int, **fields: Any) -> Schedule:
        return cls.objects.create(workspace_id=workspace_id, **fields)

    def update_fields_from(self, updates: dict[str, Any]) -> None:
        for field, value in updates.items():
            setattr(self, field, value)
        self.save(update_fields=[*updates, "updated_at"])

    def _compute_next_run(self, after: datetime | None = None) -> datetime:
        base = after or timezone.now()
        return cast("datetime", croniter(self.cron_expression, base).get_next(datetime))

    def _pause_locked(self) -> Schedule | None:
        with transaction.atomic():
            schedule = self._locked_self()
            if schedule.status == ScheduleStatus.PAUSED:
                self._sync_lifecycle_from(schedule)
                return None
            if schedule.status == ScheduleStatus.DISABLED:
                raise Conflict("Cannot pause a disabled schedule.")
            schedule.status = ScheduleStatus.PAUSED
            schedule.paused_at = timezone.now()
            schedule.next_run_at = None
            schedule.save(update_fields=("status", "paused_at", "next_run_at", "updated_at"))
            self._sync_lifecycle_from(schedule)
            return schedule

    def _resume_locked(self) -> Schedule | None:
        with transaction.atomic():
            schedule = self._locked_self()
            if schedule.status == ScheduleStatus.ACTIVE:
                self._sync_lifecycle_from(schedule)
                return None
            if schedule.status == ScheduleStatus.DISABLED:
                raise Conflict("Cannot resume a disabled schedule.")
            schedule.status = ScheduleStatus.ACTIVE
            schedule.paused_at = None
            schedule.next_run_at = schedule._compute_next_run()
            schedule.save(update_fields=("status", "paused_at", "next_run_at", "updated_at"))
            self._sync_lifecycle_from(schedule)
            return schedule

    def _locked_self(self) -> Schedule:
        if self.pk is None:
            raise Conflict("Schedule must be saved before lifecycle changes.")
        try:
            return type(self).objects.select_for_update().get(pk=self.pk)
        except type(self).DoesNotExist as exc:
            raise NotFound("Schedule not found.") from exc

    def _sync_lifecycle_from(self, schedule: Schedule) -> None:
        for field in ("status", "paused_at", "next_run_at", "updated_at"):
            setattr(self, field, getattr(schedule, field))

    def _should_compute_next_run(self) -> bool:
        return self.status == ScheduleStatus.ACTIVE and self.next_run_at is None

    def _include_update_field(self, kwargs: dict[str, Any], field: str) -> None:
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = tuple({*update_fields, field})

    def _emit_event(self, name: str, *, extra: dict[str, str] | None = None) -> None:
        props: dict[str, str] = {"schedule_id": str(self.pk), "schedule_name": self.name}
        if extra:
            props.update(extra)
        record_event(name, distinct_id=str(self.workspace_id), properties=props)
