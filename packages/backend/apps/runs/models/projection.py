from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.utils import timezone

from apps.core.exceptions import Conflict
from apps.runs.schemas.events import (
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStatus,
    RunUsage,
    UsageEvent,
)
from apps.runs.schemas.lease import LeaseUsage
from apps.runs.schemas.state import RunState

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from typing import Any
    from uuid import UUID

    from apps.runs.models.run import Run
    from apps.runs.schemas.errors import DomainErrorCode, LeaseErrorCode


class RunEventProjectionMixin:
    if TYPE_CHECKING:
        pk: int | None
        run_uid: UUID
        status: str
        state_json: dict[str, Any]
        started_at: datetime | None
        finished_at: datetime | None
        total_cost_usd: Decimal
        total_tokens: int
        sandbox_id: str
        summary: str
        error_message: str
        last_callback_at: datetime | None
        last_projected_sequence: int

        @property
        def is_terminal(self) -> bool: ...

        @property
        def projected_state(self) -> RunState | None: ...

        def save(self, *args: Any, **kwargs: Any) -> None: ...

    def _lock(self) -> None:
        fresh = type(self).objects.select_for_update().get(pk=self.pk)  # type: ignore[attr-defined]
        fields = (
            "status",
            "state_json",
            "started_at",
            "finished_at",
            "total_cost_usd",
            "total_tokens",
            "sandbox_id",
            "summary",
            "error_message",
            "last_callback_at",
            "last_projected_sequence",
        )
        for field in fields:
            setattr(self, field, getattr(fresh, field))

    def _guard_event_run(self, event: UsageEvent) -> None:
        if event.run_id != self.run_uid:
            raise Conflict("UsageEvent run_id does not match this run.")

    def _guard_not_terminal(self) -> None:
        if self.is_terminal:
            raise Conflict(f"Run is already {self.status}; no further events accepted.")

    def _write_event_row(self, event: UsageEvent, payload: dict) -> None:  # type: ignore[type-arg]
        from apps.runs.models.records import RunEvent  # noqa: PLC0415

        RunEvent.objects.create(
            run=cast("Run", self),
            sequence_no=self._next_sequence_no(),
            event_type=event.type,
            payload=payload,
        )

    def _next_sequence_no(self) -> int:
        from apps.runs.models.records import RunEvent  # noqa: PLC0415

        if self.pk is None:
            raise Conflict("Run must be saved before recording events.")
        last = (
            RunEvent.objects.filter(run_id=self.pk)
            .order_by("-sequence_no")
            .values_list("sequence_no", flat=True)
            .first()
        )
        return (last or 0) + 1

    def _project_event(self, event: UsageEvent) -> None:
        if isinstance(event, RunStarted):
            self._apply_started(event)
        elif isinstance(event, RunUsage):
            self._apply_usage(event)
        elif isinstance(event, RunFinished):
            self._apply_finished(event)
        elif isinstance(event, RunFailed):
            self._apply_failed(event)
        elif isinstance(event, RunCancelled):
            self._apply_cancelled(event)

    def _apply_started(self, event: RunStarted) -> None:
        self.status = RunStatus.RUNNING
        self.started_at = event.emitted_at or timezone.now()
        if event.sandbox_id:
            self.sandbox_id = event.sandbox_id
        self._sync_state(lease_used=LeaseUsage(), last_event_at=event.emitted_at)

    def _apply_usage(self, event: RunUsage) -> None:
        usage = LeaseUsage(
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            total_tokens=event.total_tokens,
            cost_usd=event.cost_usd,
            native_tool_calls=event.native_tool_calls,
            mcp_tool_calls=event.mcp_tool_calls,
        )
        self.total_tokens = event.total_tokens
        self.total_cost_usd = event.cost_usd
        self._sync_state(lease_used=usage, last_event_at=event.emitted_at)

    def _apply_finished(self, event: RunFinished) -> None:
        self.status = RunStatus.FINISHED
        self.finished_at = event.emitted_at or timezone.now()
        self.total_tokens = event.final_total_tokens
        self.total_cost_usd = event.final_cost_usd
        self._sync_state(lease_used=self._finished_usage(event), last_event_at=event.emitted_at)

    def _apply_failed(self, event: RunFailed) -> None:
        self.status = RunStatus.FAILED
        self.finished_at = event.emitted_at or timezone.now()
        self.error_message = event.error
        self.total_cost_usd = event.final_cost_usd
        self._sync_state(
            lease_used=self._usage_with_final_cost(event.final_cost_usd),
            last_event_at=event.emitted_at,
            error_code=event.error_code,
        )

    def _apply_cancelled(self, event: RunCancelled) -> None:
        self.status = RunStatus.CANCELLED
        self.finished_at = event.emitted_at or timezone.now()
        self.total_cost_usd = event.final_cost_usd
        self._sync_state(
            lease_used=self._usage_with_final_cost(event.final_cost_usd),
            last_event_at=event.emitted_at,
        )

    def _finished_usage(self, event: RunFinished) -> LeaseUsage:
        return LeaseUsage(
            input_tokens=event.final_input_tokens,
            output_tokens=event.final_output_tokens,
            total_tokens=event.final_total_tokens,
            cost_usd=event.final_cost_usd,
        )

    def _usage_with_final_cost(self, cost_usd: Decimal) -> LeaseUsage:
        current = self.projected_state
        if current is None:
            return LeaseUsage(cost_usd=cost_usd)
        return current.lease_used.model_copy(update={"cost_usd": cost_usd})

    def _sync_state(
        self,
        *,
        lease_used: LeaseUsage | None = None,
        last_event_at: datetime | None = None,
        error_code: LeaseErrorCode | DomainErrorCode | None = None,
    ) -> None:
        current = self.projected_state
        used = lease_used or (current.lease_used if current else LeaseUsage())
        self.state_json = RunState(
            run_id=self.run_uid,
            status=RunStatus(self.status),
            started_at=self.started_at,
            finished_at=self.finished_at,
            lease_used=used,
            last_event_at=last_event_at or timezone.now(),
            summary=self.summary,
            error_code=error_code or (current.error_code if current else None),
        ).model_dump(mode="json")

    def _persist_after_event(self, event: UsageEvent) -> None:
        fields = [
            "status",
            "state_json",
            "total_tokens",
            "total_cost_usd",
            "updated_at",
        ]
        if isinstance(event, RunStarted):
            fields.extend(["started_at", "sandbox_id"])
        if isinstance(event, (RunFinished, RunFailed, RunCancelled)):
            fields.extend(["finished_at"])
        if isinstance(event, RunFailed):
            fields.append("error_message")
        self.save(update_fields=fields)
