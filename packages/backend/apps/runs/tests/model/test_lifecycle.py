from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.core.exceptions import Conflict
from apps.runs.factories import RunFactory
from apps.runs.models import Run, RunEvent
from apps.runs.schemas.events import RunStatus

pytestmark = pytest.mark.django_db


def test_record_run_started_transitions_to_running() -> None:
    run = RunFactory()
    run.record_event({"type": "run_started", "run_id": str(run.run_uid), "sandbox_id": "sbx-1"})
    run.refresh_from_db()
    assert run.status == RunStatus.RUNNING
    assert run.started_at is not None
    assert run.sandbox_id == "sbx-1"


def test_record_run_usage_updates_totals() -> None:
    run = RunFactory(running=True)
    run.record_event(
        {
            "type": "run_usage",
            "run_id": str(run.run_uid),
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "cost_usd": "0.0025",
            "native_tool_calls": 1,
            "mcp_tool_calls": 0,
        }
    )
    run.refresh_from_db()
    assert run.total_tokens == 150
    assert run.total_cost_usd == Decimal("0.0025")
    state = run.projected_state
    assert state is not None
    assert state.lease_used.total_tokens == 150


def test_record_run_completed_transitions_to_finished() -> None:
    run = RunFactory(running=True)
    run.record_event(
        {
            "type": "run_completed",
            "run_id": str(run.run_uid),
            "final_input_tokens": 200,
            "final_output_tokens": 100,
            "final_total_tokens": 300,
            "final_cost_usd": "0.05",
        }
    )
    run.refresh_from_db()
    assert run.status == RunStatus.FINISHED
    assert run.finished_at is not None
    assert run.total_cost_usd == Decimal("0.05")
    assert run.total_tokens == 300
    assert run.is_terminal
    state = run.projected_state
    assert state is not None
    assert state.status == RunStatus.FINISHED
    assert state.finished_at is not None
    assert state.lease_used.total_tokens == 300
    assert state.lease_used.cost_usd == Decimal("0.05")


def test_record_run_failed_transitions_to_failed() -> None:
    run = RunFactory(running=True)
    run.record_event(
        {
            "type": "run_failed",
            "run_id": str(run.run_uid),
            "error": "Tool execution timed out",
            "error_code": "tool_failed",
            "final_cost_usd": "0.01",
        }
    )
    run.refresh_from_db()
    assert run.status == RunStatus.FAILED
    assert run.error_message == "Tool execution timed out"
    assert run.is_terminal
    state = run.projected_state
    assert state is not None
    assert state.status == RunStatus.FAILED
    assert state.error_code == "tool_failed"


def test_record_run_cancelled_transitions_to_cancelled() -> None:
    run = RunFactory(running=True)
    run.record_event(
        {
            "type": "run_cancelled",
            "run_id": str(run.run_uid),
            "final_cost_usd": "0.00",
        }
    )
    run.refresh_from_db()
    assert run.status == RunStatus.CANCELLED
    assert run.is_terminal


def test_record_event_rejects_on_terminal_run() -> None:
    run = RunFactory(finished=True)
    with pytest.raises(Conflict, match="already"):
        run.record_event({"type": "run_usage", "run_id": str(run.run_uid)})


def test_record_event_rejects_mismatched_run_id() -> None:
    run = RunFactory()
    with pytest.raises(Conflict, match="does not match"):
        run.record_event({"type": "run_started", "run_id": str(uuid.uuid4())})
    assert RunEvent.objects.filter(run=run).count() == 0


def test_record_event_refreshes_locked_projection_fields() -> None:
    run = RunFactory()
    stale = Run.objects.get(pk=run.pk)
    run.record_event({"type": "run_started", "run_id": str(run.run_uid)})
    stale.record_event(
        {
            "type": "run_usage",
            "run_id": str(stale.run_uid),
            "total_tokens": 25,
            "cost_usd": "0.003",
        }
    )
    stale.refresh_from_db()
    state = stale.projected_state
    assert state is not None
    assert state.started_at is not None
    assert state.status == RunStatus.RUNNING


def test_run_events_accumulate_as_rows() -> None:
    run = RunFactory()
    run.record_event({"type": "run_started", "run_id": str(run.run_uid)})
    run.record_event(
        {
            "type": "run_usage",
            "run_id": str(run.run_uid),
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "cost_usd": "0.001",
        }
    )
    events = list(RunEvent.objects.for_run(run.pk))
    assert len(events) == 2
    assert events[0].event_type == "run_started"
    assert events[0].sequence_no == 1
    assert events[1].event_type == "run_usage"
    assert events[1].sequence_no == 2


def test_run_event_is_append_only() -> None:
    run = RunFactory()
    run.record_event({"type": "run_started", "run_id": str(run.run_uid)})
    event = RunEvent.objects.for_run(run.pk).first()
    assert event is not None
    with pytest.raises(Conflict, match="append-only"):
        event.save()
    with pytest.raises(Conflict, match="append-only"):
        event.delete()
