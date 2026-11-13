from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import Action
from apps.core.events import record_event
from apps.core.exceptions import Conflict, NotFound
from apps.core.models import TimestampedModel
from apps.insights.models.queryset import (
    InsightAffectedData,
    InsightCategory,
    InsightCategoryCountData,
    InsightQuerySet,
    InsightStatus,
    InsightSummaryData,
)

if TYPE_CHECKING:
    from apps.workspaces.models.member import WorkspaceMember


class Insight(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="insights",
    )
    category = models.CharField(
        max_length=24,
        choices=InsightCategory,
        db_index=True,
    )
    title = models.CharField(max_length=200)
    body = models.TextField(max_length=4_000)
    status = models.CharField(
        max_length=12,
        choices=InsightStatus,
        default=InsightStatus.ACTIVE,
        db_index=True,
    )
    affected_agent_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Agent PKs referenced by this insight.",
    )
    affected_run_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Run UUIDs referenced by this insight.",
    )
    affected_end_user_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="EndUser PKs referenced by this insight.",
    )
    dismissed_at = models.DateTimeField(blank=True, null=True)
    dismissed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    pinned_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()
    objects = InsightQuerySet.as_manager()

    class Meta:
        db_table = "insights_insight"
        ordering = ("-created_at",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(category__in=InsightCategory.values),
                name="insight_category_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=InsightStatus.values),
                name="insight_status_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(title=""),
                name="insight_title_non_empty",
            ),
            models.CheckConstraint(
                condition=~models.Q(body=""),
                name="insight_body_non_empty",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "-created_at")),
            models.Index(fields=("workspace", "status")),
            models.Index(fields=("workspace", "category")),
        ]

    def __str__(self) -> str:
        return f"[{self.category}] {self.title}"

    def clean(self) -> None:
        self._validate_affected_id_lists()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    @classmethod
    def list_for_workspace(
        cls,
        workspace_id: int,
        *,
        category: str | None = None,
        status: str | None = None,
    ) -> InsightQuerySet:
        qs = cls.objects.for_workspace(workspace_id)
        if category is not None:
            qs = qs.by_category(category)
        qs = qs.filter(status=status) if status is not None else qs.visible()
        return qs

    @classmethod
    def get_for_workspace(cls, workspace_id: int, pk: int | str) -> Insight | None:
        return cls.objects.for_workspace(workspace_id).filter(pk=pk).first()

    @classmethod
    def get_for_workspace_or_raise(cls, workspace_id: int, pk: int | str) -> Insight:
        try:
            return cls.objects.for_workspace(workspace_id).get(pk=pk)
        except cls.DoesNotExist as exc:
            raise NotFound("Insight not found.") from exc

    @classmethod
    def summary_for_workspace(cls, workspace_id: int) -> InsightSummaryData:
        qs = cls.objects.for_workspace(workspace_id)
        agg = qs.aggregate(
            total_active=models.Count("id", filter=models.Q(status=InsightStatus.ACTIVE)),
            total_pinned=models.Count("id", filter=models.Q(status=InsightStatus.PINNED)),
        )
        distribution = (
            qs.visible().values("category").annotate(count=models.Count("id")).order_by("category")
        )
        return {
            "total_active": agg["total_active"],
            "total_pinned": agg["total_pinned"],
            "by_category": [
                InsightCategoryCountData(category=row["category"], count=row["count"])
                for row in distribution
            ],
        }

    @classmethod
    def generate(
        cls,
        *,
        workspace_id: int,
        category: str,
        title: str,
        body: str,
        affected: InsightAffectedData | None = None,
    ) -> Insight:
        insight = cls._create_generated(
            workspace_id=workspace_id,
            category=category,
            title=title,
            body=body,
            affected=affected or {},
        )
        cls._record_generated(workspace_id, insight, category)
        return insight

    @classmethod
    def _create_generated(
        cls,
        *,
        workspace_id: int,
        category: str,
        title: str,
        body: str,
        affected: InsightAffectedData,
    ) -> Insight:
        return cls.objects.create(
            workspace_id=workspace_id,
            category=category,
            title=title,
            body=body,
            affected_agent_ids=affected.get("affected_agent_ids", []),
            affected_run_ids=affected.get("affected_run_ids", []),
            affected_end_user_ids=affected.get("affected_end_user_ids", []),
        )

    @staticmethod
    def _record_generated(workspace_id: int, insight: Insight, category: str) -> None:
        record_event(
            "insight_generated",
            distinct_id=str(workspace_id),
            properties={"insight_id": str(insight.pk), "category": category},
        )

    @transaction.atomic
    def dismiss(self, *, user_id: int) -> None:
        self._refresh_locked()
        if self.status == InsightStatus.DISMISSED:
            raise Conflict("Insight is already dismissed.")
        self.status = InsightStatus.DISMISSED
        self.dismissed_at = timezone.now()
        self.dismissed_by_id = user_id
        self.pinned_at = None
        self.save(
            update_fields=("status", "dismissed_at", "dismissed_by_id", "pinned_at", "updated_at")
        )
        self._emit_event("insight_dismissed")

    @transaction.atomic
    def pin(self) -> None:
        self._refresh_locked()
        if self.status == InsightStatus.PINNED:
            raise Conflict("Insight is already pinned.")
        if self.status == InsightStatus.DISMISSED:
            raise Conflict("Dismissed insights cannot be pinned.")
        self.status = InsightStatus.PINNED
        self.pinned_at = timezone.now()
        self.save(update_fields=("status", "pinned_at", "updated_at"))
        self._emit_event("insight_pinned")

    @transaction.atomic
    def unpin(self) -> None:
        self._refresh_locked()
        if self.status != InsightStatus.PINNED:
            raise Conflict("Insight is not pinned.")
        self.status = InsightStatus.ACTIVE
        self.pinned_at = None
        self.save(update_fields=("status", "pinned_at", "updated_at"))
        self._emit_event("insight_unpinned")

    def can_be_viewed_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.INSIGHTS_READ)

    def _refresh_locked(self) -> None:
        self.refresh_from_db(from_queryset=type(self).objects.select_for_update())

    def _emit_event(self, name: str) -> None:
        record_event(
            name,
            distinct_id=str(self.workspace_id),
            properties={
                "insight_id": str(self.pk),
                "category": self.category,
            },
        )

    def _validate_affected_id_lists(self) -> None:
        errors: dict[str, str] = {}
        self._collect_int_list_error(errors, "affected_agent_ids")
        self._collect_int_list_error(errors, "affected_end_user_ids")
        self._collect_run_id_error(errors)
        if errors:
            raise ValidationError(errors)

    def _collect_int_list_error(self, errors: dict[str, str], field: str) -> None:
        values = getattr(self, field)
        if not isinstance(values, list):
            errors[field] = "Must be a list of positive integer IDs."
            return
        if not all(isinstance(value, int) and value > 0 for value in values):
            errors[field] = "Must contain only positive integer IDs."

    def _collect_run_id_error(self, errors: dict[str, str]) -> None:
        if not isinstance(self.affected_run_ids, list):
            errors["affected_run_ids"] = "Must be a list of run UUIDs."
            return
        if not all(self._is_uuid(value) for value in self.affected_run_ids):
            errors["affected_run_ids"] = "Must contain only run UUID strings."

    def _is_uuid(self, value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            uuid.UUID(value)
        except ValueError:
            return False
        return True
