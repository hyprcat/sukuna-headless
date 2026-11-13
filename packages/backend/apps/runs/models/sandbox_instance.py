from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.core.exceptions import Conflict
from apps.core.models import TimestampedModel
from apps.runs.schemas.config import SandboxTransitionRules

if TYPE_CHECKING:
    import uuid

    from apps.runs.models.run import Run


class SandboxState(models.TextChoices):
    SPAWNING = "spawning"
    BOOTING = "booting"
    PAUSED = "paused"
    RUNNING = "running"
    TERMINATED = "terminated"


class SandboxInstanceQuerySet(models.QuerySet["SandboxInstance"]):
    def for_workspace(self, workspace_id: int) -> SandboxInstanceQuerySet:
        return self.filter(workspace_id=workspace_id)

    def warm(self) -> SandboxInstanceQuerySet:
        return self.filter(
            sandbox_state=SandboxState.PAUSED,
            current_run__isnull=True,
        )

    def for_agent(self, agent_id: int) -> SandboxInstanceQuerySet:
        return self.filter(agent_id=agent_id)

    def for_conversation(self, conversation_id: uuid.UUID | str) -> SandboxInstanceQuerySet:
        return self.filter(conversation_id=conversation_id)

    def idle_past(self, seconds: int) -> SandboxInstanceQuerySet:
        cutoff = timezone.now() - timedelta(seconds=seconds)
        return self.filter(
            sandbox_state=SandboxState.PAUSED,
            current_run__isnull=True,
            last_run_finished_at__lte=cutoff,
        )


class SandboxInstance(TimestampedModel):
    sandbox_id = models.CharField(max_length=128, unique=True)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="sandbox_instances",
    )
    agent = models.ForeignKey(
        "agents.Agent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sandbox_instances",
    )
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    sandbox_state = models.CharField(
        max_length=16,
        choices=SandboxState,
        default=SandboxState.SPAWNING,
        db_index=True,
    )
    sandbox_url = models.URLField(max_length=512, blank=True, default="")
    current_run = models.ForeignKey(
        "runs.Run",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sandbox_instance_set",
    )
    last_run_finished_at = models.DateTimeField(null=True, blank=True)
    delayed_termination_at = models.DateTimeField(null=True, blank=True)
    boot_started_at = models.DateTimeField(null=True, blank=True)
    boot_completed_at = models.DateTimeField(null=True, blank=True)
    pause_count = models.PositiveIntegerField(default=0)
    resume_count = models.PositiveIntegerField(default=0)

    history = HistoricalRecords()
    objects = SandboxInstanceQuerySet.as_manager()

    class Meta:
        db_table = "runs_sandbox_instance"
        ordering = ("-created_at",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("agent", "sandbox_state")),
            models.Index(fields=("sandbox_state", "last_run_finished_at")),
        ]

    def __str__(self) -> str:
        return f"Sandbox {self.sandbox_id} [{self.sandbox_state}]"

    def _guard_transition(self, target: str) -> None:
        allowed = SandboxTransitionRules().forward.get(self.sandbox_state, frozenset())
        if target not in allowed:
            raise Conflict(f"Cannot transition from {self.sandbox_state} to {target}.")

    def mark_booted(self) -> None:
        self._guard_transition(SandboxState.RUNNING)
        now = timezone.now()
        self.sandbox_state = SandboxState.RUNNING
        self.boot_completed_at = now
        self.save(update_fields=("sandbox_state", "boot_completed_at", "updated_at"))

    def mark_running(self, run: Run) -> None:
        self._guard_transition(SandboxState.RUNNING)
        self._guard_run_binding(run)
        self.sandbox_state = SandboxState.RUNNING
        self.current_run = run
        self.resume_count += 1
        self.save(
            update_fields=(
                "sandbox_state",
                "current_run",
                "resume_count",
                "updated_at",
            )
        )

    def mark_paused(self) -> None:
        self._guard_transition(SandboxState.PAUSED)
        now = timezone.now()
        self.sandbox_state = SandboxState.PAUSED
        self.current_run = None
        self.last_run_finished_at = now
        self.pause_count += 1
        self.save(
            update_fields=(
                "sandbox_state",
                "current_run",
                "last_run_finished_at",
                "pause_count",
                "updated_at",
            )
        )

    def mark_terminated(self) -> None:
        self._guard_transition(SandboxState.TERMINATED)
        self.sandbox_state = SandboxState.TERMINATED
        self.current_run = None
        self.save(update_fields=("sandbox_state", "current_run", "updated_at"))

    def _guard_run_binding(self, run: Run) -> None:
        if run.workspace_id != self.workspace_id:
            raise Conflict("Run workspace must match sandbox workspace.")
        if self.agent_id and run.agent_id != self.agent_id:
            raise Conflict("Run agent must match sandbox agent.")
        if self.conversation_id and not self._run_matches_conversation(run):
            raise Conflict("Run conversation must match sandbox conversation.")

    def _run_matches_conversation(self, run: Run) -> bool:
        return bool(
            run.conversation_id
            and run.conversation
            and run.conversation.conversation_uid == self.conversation_id
        )
