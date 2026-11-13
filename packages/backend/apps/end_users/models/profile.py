from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Any, ClassVar, cast

from croniter import croniter  # type: ignore[import-untyped]  # croniter ships no stubs.
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.core.exceptions import NotFound
from apps.core.models import TimestampedModel
from apps.end_users.schemas.config import EndUserFormat


class RunCountPeriod(models.TextChoices):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class ControlProfile(TimestampedModel):
    end_user = models.OneToOneField(
        "end_users.EndUser",
        on_delete=models.CASCADE,
        related_name="profile",
    )
    credits = models.IntegerField(default=0)
    credit_grant_per_period = models.PositiveIntegerField(
        default=0,
        help_text="Credits added on each scheduled refresh.",
    )
    run_count_limit = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Max runs per period. Null = unlimited.",
    )
    run_count_period = models.CharField(
        max_length=8, choices=RunCountPeriod, blank=True, default=""
    )
    runs_used_in_period = models.PositiveIntegerField(default=0)
    sandbox_time_seconds = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Max seconds per run. Null = workspace default.",
    )
    concurrency_max = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        help_text="Max simultaneous runs. Null = unlimited.",
    )
    model_tier = models.CharField(max_length=40, default="free")
    allowed_tools = models.ManyToManyField(
        "tools.Tool",
        blank=True,
        related_name="authorized_end_users",
        help_text="Empty = unrestricted (all workspace tools).",
    )
    allowed_knowledge = models.ManyToManyField(
        "knowledge.Knowledge",
        blank=True,
        related_name="authorized_end_users",
        help_text="Empty = unrestricted (all workspace knowledge).",
    )
    credit_refresh_schedule = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text="Preset (daily/weekly/monthly) or cron expression. Empty = never.",
    )
    next_credit_refresh_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Computed next refresh time. Used by the beat job.",
    )
    history = HistoricalRecords()

    class Meta:
        db_table = "end_users_controlprofile"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(credits__gte=0),
                name="end_users_profile_credits_non_negative",
            ),
            models.CheckConstraint(
                condition=~Q(model_tier=""),
                name="end_users_profile_model_tier_non_empty",
            ),
            models.CheckConstraint(
                condition=(
                    Q(run_count_limit__isnull=True, run_count_period="")
                    | Q(run_count_limit__isnull=False, run_count_period__in=RunCountPeriod.values)
                ),
                name="end_users_profile_run_count_config_valid",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("next_credit_refresh_at",)),
        ]

    def __str__(self) -> str:
        return f"Controls[{self.end_user_id}]"

    def clean(self) -> None:
        self._validate_credits()
        self._validate_run_count_config()
        self._validate_refresh_schedule()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def refresh_is_due(self) -> bool:
        if self.next_credit_refresh_at is None:
            return False
        if self.next_credit_refresh_at > timezone.now():
            return False
        return self.credit_refresh_schedule not in {"", "never"}

    def update_controls(self, *, workspace_id: int, **fields: Any) -> None:
        """Update control profile fields atomically.

        Only keys present in *fields* are changed. Scalar fields are
        set directly; ``allowed_tool_ids`` / ``allowed_knowledge_ids``
        go through M2M ``.set()``.
        """
        with transaction.atomic():
            profile = type(self).objects.select_for_update().get(pk=self.pk)
            profile._apply_scalar_controls(fields)
            profile._apply_m2m_controls(fields, workspace_id)
        self.refresh_from_db()

    def _apply_scalar_controls(self, fields: dict[str, Any]) -> None:
        changed: list[str] = []
        for name in EndUserFormat().control_update_fields:
            if name not in fields:
                continue
            val = fields[name]
            if val is None:
                field = cast("models.Field[Any, Any]", self._meta.get_field(name))
                val = field.get_default()
            setattr(self, name, val)
            changed.append(name)
        self._sync_refresh_schedule(changed)
        if changed:
            self.save(update_fields=[*changed, "updated_at"])

    def _sync_refresh_schedule(self, changed: list[str]) -> None:
        if "credit_refresh_schedule" not in changed:
            return
        self.full_clean(validate_unique=False, validate_constraints=False)
        self.next_credit_refresh_at = _next_refresh_start(self.credit_refresh_schedule)
        changed.append("next_credit_refresh_at")

    def _apply_m2m_controls(self, fields: dict[str, Any], workspace_id: int) -> None:
        from apps.knowledge.models import Knowledge  # noqa: PLC0415
        from apps.tools.models import Tool  # noqa: PLC0415

        if "allowed_tool_ids" in fields:
            ids = fields["allowed_tool_ids"] or []
            tools = Tool.objects.filter(pk__in=ids, workspace_id=workspace_id)
            self._guard_all_ids_found(tools, ids, "Tool")
            self.allowed_tools.set(tools)
        if "allowed_knowledge_ids" in fields:
            ids = fields["allowed_knowledge_ids"] or []
            knowledge = Knowledge.objects.filter(pk__in=ids, workspace_id=workspace_id)
            self._guard_all_ids_found(knowledge, ids, "Knowledge base")
            self.allowed_knowledge.set(knowledge)

    def _guard_all_ids_found(self, qs: models.QuerySet[Any], ids: list[int], label: str) -> None:
        if qs.count() != len(set(ids)):
            raise NotFound(f"{label} not found.")

    def apply_credit_refresh(self) -> None:
        if self.next_credit_refresh_at is None:
            return
        self.credits += self.credit_grant_per_period
        self.runs_used_in_period = 0
        self.next_credit_refresh_at = _next_refresh_boundary(
            self.next_credit_refresh_at, self.credit_refresh_schedule
        )
        self.save(
            update_fields=("credits", "runs_used_in_period", "next_credit_refresh_at", "updated_at")
        )

    def _validate_credits(self) -> None:
        if self.credits < 0:
            raise ValidationError({"credits": "Credits must be zero or greater."})

    def _validate_run_count_config(self) -> None:
        has_limit = self.run_count_limit is not None
        has_period = bool(self.run_count_period)
        if has_limit != has_period:
            raise ValidationError(
                "run_count_limit and run_count_period must both be set or both be empty."
            )

    def _validate_refresh_schedule(self) -> None:
        if self.credit_refresh_schedule in EndUserFormat().refresh_schedule_presets:
            return
        if not croniter.is_valid(self.credit_refresh_schedule, strict=True):
            raise ValidationError({"credit_refresh_schedule": "Invalid refresh schedule."})


def _next_refresh_boundary(current: datetime, schedule: str) -> datetime:
    if schedule == "daily":
        return _next_after_now(current, timedelta(days=1))
    if schedule == "weekly":
        return _next_after_now(current, timedelta(weeks=1))
    if schedule == "monthly":
        return _next_monthly_after_now(current)
    return _next_cron_after_now(current, schedule)


def _next_refresh_start(schedule: str) -> datetime | None:
    if schedule in {"", "never"}:
        return None
    return _next_refresh_boundary(timezone.now(), schedule)


def _next_after_now(current: datetime, delta: timedelta) -> datetime:
    now = timezone.now()
    next_at = current
    while next_at <= now:
        next_at += delta
    return next_at


def _next_monthly_after_now(current: datetime) -> datetime:
    now = timezone.now()
    next_at = current
    while next_at <= now:
        next_at = _add_month(next_at)
    return next_at


def _next_cron_after_now(current: datetime, schedule: str) -> datetime:
    now = timezone.now()
    next_at = current
    while next_at <= now:
        next_at = cast("datetime", croniter(schedule, next_at).get_next(datetime))
    return next_at


def _add_month(value: datetime) -> datetime:
    month = value.month + 1
    year = value.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
