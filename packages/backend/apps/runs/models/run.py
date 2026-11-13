from __future__ import annotations

import uuid
from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, ClassVar

from django.db import models, transaction
from django.utils import timezone
from pydantic import TypeAdapter
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import Action
from apps.billing.schemas import BillingFormat
from apps.core.events import record_event
from apps.core.models import TimestampedModel
from apps.runs.models.projection import RunEventProjectionMixin
from apps.runs.schemas.events import RunStatus, UsageEvent
from apps.runs.schemas.lease import Lease
from apps.runs.schemas.state import RunState

if TYPE_CHECKING:
    from apps.workspaces.models.member import WorkspaceMember


@lru_cache(maxsize=1)
def _get_event_adapter() -> TypeAdapter[UsageEvent]:
    return TypeAdapter(UsageEvent)


class RunQuerySet(models.QuerySet["Run"]):
    def for_workspace(self, workspace_id: int) -> RunQuerySet:
        return self.filter(workspace_id=workspace_id)

    def active(self) -> RunQuerySet:
        return self.filter(status__in=(RunStatus.QUEUED, RunStatus.RUNNING))

    def terminal(self) -> RunQuerySet:
        return self.filter(status__in=(RunStatus.FINISHED, RunStatus.FAILED, RunStatus.CANCELLED))

    def for_end_user(self, end_user_id: int) -> RunQuerySet:
        return self.filter(end_user_id=end_user_id)

    def for_conversation(self, conversation_id: int) -> RunQuerySet:
        return self.filter(conversation_id=conversation_id)

    def active_count_for_end_user(self, end_user_id: int) -> int:
        return self.for_end_user(end_user_id).active().count()


class Run(RunEventProjectionMixin, TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="runs",
    )
    agent = models.ForeignKey("agents.Agent", on_delete=models.CASCADE, related_name="runs")
    end_user = models.ForeignKey("end_users.EndUser", on_delete=models.CASCADE, related_name="runs")
    run_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    conversation = models.ForeignKey(
        "runs.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    prompt = models.TextField(max_length=64_000)
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in RunStatus],
        default=RunStatus.QUEUED,
        db_index=True,
    )
    sandbox_id = models.CharField(max_length=128, blank=True, default="")
    lease_json = models.JSONField(
        default=dict,
        help_text="Frozen Lease sent to the sandbox at start.",
    )
    state_json = models.JSONField(
        default=dict,
        help_text="Projected RunState — updated by record_event.",
    )
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    total_cost_usd = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    total_cost_currency = models.CharField(max_length=3, default=BillingFormat().currency)
    total_tokens = models.IntegerField(default=0)
    summary = models.TextField(blank=True, default="", max_length=4_000)
    error_message = models.TextField(blank=True, default="")
    is_scheduled = models.BooleanField(default=False)
    manifest_id = models.UUIDField(null=True, blank=True, db_index=True)
    last_callback_at = models.DateTimeField(null=True, blank=True)
    last_projected_sequence = models.PositiveIntegerField(default=0)
    history = HistoricalRecords()
    objects = RunQuerySet.as_manager()

    class Meta:
        db_table = "runs_run"
        ordering = ("-created_at",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(total_cost_usd__gte=Decimal("0")),
                name="runs_run_cost_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_cost_currency=BillingFormat().currency),
                name="runs_run_cost_currency_usd",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "-created_at")),
            models.Index(fields=("workspace", "status")),
            models.Index(fields=("end_user", "status")),
            models.Index(fields=("agent", "-created_at")),
        ]

    def __str__(self) -> str:
        return f"Run {self.run_uid} [{self.status}]"

    @property
    def is_terminal(self) -> bool:
        return self.status in (RunStatus.FINISHED, RunStatus.FAILED, RunStatus.CANCELLED)

    @property
    def lease(self) -> Lease | None:
        if not self.lease_json:
            return None
        return Lease.model_validate(self.lease_json)

    @property
    def projected_state(self) -> RunState | None:
        if not self.state_json:
            return None
        return RunState.model_validate(self.state_json)

    def set_lease(self, lease: Lease) -> None:
        self.lease_json = lease.model_dump(mode="json")
        self.save(update_fields=("lease_json", "updated_at"))

    @transaction.atomic
    def record_event(self, payload: dict) -> None:  # type: ignore[type-arg]
        event = _get_event_adapter().validate_python(payload)
        self._guard_event_run(event)
        self._lock()
        self._guard_not_terminal()
        self._write_event_row(event, payload)
        self._project_event(event)
        self._persist_after_event(event)
        self._emit_posthog_event(event)

    @transaction.atomic
    def cancel(self) -> None:
        self._lock()
        self._guard_not_terminal()
        now = timezone.now()
        self.status = RunStatus.CANCELLED
        self.finished_at = now
        self._sync_state(last_event_at=now)
        self.save(update_fields=("status", "finished_at", "state_json", "updated_at"))
        self._emit_analytics("run_cancelled")

    @classmethod
    def list_for_workspace(
        cls,
        workspace_id: int,
        *,
        status: str | None = None,
        agent_id: int | None = None,
        end_user_id: int | None = None,
    ) -> RunQuerySet:
        qs = cls.objects.for_workspace(workspace_id).select_related(
            "agent",
            "end_user",
            "rating",
        )
        if status is not None:
            qs = qs.filter(status=status)
        if agent_id is not None:
            qs = qs.filter(agent_id=agent_id)
        if end_user_id is not None:
            qs = qs.for_end_user(end_user_id)
        return qs

    @classmethod
    def get_for_workspace(cls, workspace_id: int, pk: int) -> Run | None:
        return cls._detail_queryset(workspace_id).filter(pk=pk).first()

    @classmethod
    def get_by_uid(cls, workspace_id: int, run_uid: uuid.UUID) -> Run | None:
        return cls._detail_queryset(workspace_id).filter(run_uid=run_uid).first()

    @classmethod
    def _detail_queryset(cls, workspace_id: int) -> RunQuerySet:
        return cls.objects.for_workspace(workspace_id).select_related(
            "agent",
            "end_user",
            "rating",
        )

    def can_be_viewed_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.RUNS_READ)

    def _emit_analytics(self, name: str, extra: dict[str, str] | None = None) -> None:
        props: dict[str, str] = {
            "run_id": str(self.run_uid),
            "agent_id": str(self.agent_id),
            "end_user_id": str(self.end_user_id),
            "status": self.status,
        }
        if extra:
            props.update(extra)
        record_event(name, distinct_id=str(self.workspace_id), properties=props)

    def _emit_posthog_event(self, event: UsageEvent) -> None:
        name = f"run_{event.type.removeprefix('run_')}"
        self._emit_analytics(name)
