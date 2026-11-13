"""Tests for callback ingestion: happy-path flows, billing settlement, state."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import TestCase

from apps.billing.factories import BillingHoldFactory
from apps.billing.models.hold import HoldStatus
from apps.runs.factories import SandboxInstanceFactory
from apps.runs.models.records import RunEvent
from apps.runs.models.sandbox_instance import SandboxState
from apps.runs.schemas.events import RunStatus
from apps.runs.services.callbacks import verify_and_ingest
from apps.runs.tests.service.conftest import (
    final_usage,
    make_batch,
    make_event,
    setup_run_with_manifest,
    started_payload,
    usage_payload,
)

pytestmark = pytest.mark.django_db


class TestValidBatchIngestion(TestCase):
    def test_events_projected_and_acked(self):
        run, record, key, _ = setup_run_with_manifest()
        events = [
            make_event(1, "run_started", started_payload()),
            make_event(2, "step", {"step_index": 0, "reasoning": "...", "output": "hi"}),
            make_event(3, "usage_checkpoint", usage_payload(100, "0.01")),
        ]
        body = make_batch(run, record, events, key)
        result = verify_and_ingest(body)

        assert result["acked_through"] == 3
        assert result["status"] == "ok"
        assert RunEvent.objects.filter(run=run).count() == 3

        run.refresh_from_db()
        assert run.status == RunStatus.RUNNING
        assert run.last_projected_sequence == 3
        assert run.last_callback_at is not None
        assert run.total_tokens == 100

    def test_terminal_run_completed_settles_hold(self):
        run, record, key, wallet = setup_run_with_manifest()
        hold = BillingHoldFactory(run=run, wallet=wallet, amount_reserved_usd=Decimal("10.00"))
        events = [
            make_event(1, "run_started", started_payload()),
            make_event(
                2,
                "run_completed",
                {
                    "final_usage": final_usage(500, "0.50"),
                    "summary": "Done",
                },
            ),
        ]
        body = make_batch(run, record, events, key)
        result = verify_and_ingest(body)

        assert result["acked_through"] == 2
        run.refresh_from_db()
        assert run.status == RunStatus.FINISHED
        assert run.total_cost_usd == Decimal("0.50")

        hold.refresh_from_db()
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("0.50")

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("99.50")

    def test_terminal_run_failed_releases_hold(self):
        run, record, key, wallet = setup_run_with_manifest()
        hold = BillingHoldFactory(run=run, wallet=wallet, amount_reserved_usd=Decimal("10.00"))
        events = [
            make_event(1, "run_started", started_payload()),
            make_event(
                2,
                "run_failed",
                {
                    "error_code": "tool_failed",
                    "message": "Tool crashed",
                    "final_usage": final_usage(50, "0.00"),
                },
            ),
        ]
        body = make_batch(run, record, events, key)
        result = verify_and_ingest(body)

        assert result["acked_through"] == 2
        run.refresh_from_db()
        assert run.status == RunStatus.FAILED
        assert run.error_message == "Tool crashed"

        hold.refresh_from_db()
        assert hold.status == HoldStatus.RELEASED

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("100.00")

    def test_terminal_run_cancelled_settles_hold(self):
        run, record, key, wallet = setup_run_with_manifest()
        hold = BillingHoldFactory(run=run, wallet=wallet, amount_reserved_usd=Decimal("10.00"))
        events = [
            make_event(1, "run_started", started_payload()),
            make_event(
                2,
                "run_cancelled",
                {
                    "reason": "user_requested",
                    "final_usage": final_usage(200, "0.20"),
                },
            ),
        ]
        body = make_batch(run, record, events, key)
        verify_and_ingest(body)

        hold.refresh_from_db()
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("0.20")


class TestSandboxStateUpdate(TestCase):
    def test_terminal_event_pauses_sandbox(self):
        run, record, key, wallet = setup_run_with_manifest()
        BillingHoldFactory(run=run, wallet=wallet, amount_reserved_usd=Decimal("10.00"))
        instance = SandboxInstanceFactory(
            running=True,
            workspace=run.workspace,
            agent=run.agent,
        )
        instance.current_run = run
        instance.save(update_fields=["current_run"])

        events = [
            make_event(1, "run_started", started_payload()),
            make_event(
                2,
                "run_completed",
                {
                    "final_usage": final_usage(500, "0.50"),
                    "summary": "Done",
                },
            ),
        ]
        body = make_batch(run, record, events, key)
        verify_and_ingest(body)

        instance.refresh_from_db()
        assert instance.sandbox_state == SandboxState.PAUSED
        assert instance.current_run is None


class TestMixedEventTypes(TestCase):
    def test_batch_with_all_event_types(self):
        run, record, key, wallet = setup_run_with_manifest()
        BillingHoldFactory(run=run, wallet=wallet, amount_reserved_usd=Decimal("10.00"))
        events = [
            make_event(1, "run_started", started_payload()),
            make_event(2, "step", {"step_index": 0, "reasoning": "x", "output": "y"}),
            make_event(3, "tool_call", {"call_id": "c1", "tool_name": "search", "arguments": {}}),
            make_event(
                4,
                "tool_result",
                {"call_id": "c1", "tool_name": "search", "result": "data", "duration_ms": 200},
            ),
            make_event(5, "usage_checkpoint", usage_payload(300, "0.30")),
            make_event(
                6,
                "run_completed",
                {"final_usage": final_usage(400, "0.40"), "summary": "All done"},
            ),
        ]
        body = make_batch(run, record, events, key)
        result = verify_and_ingest(body)

        assert result["acked_through"] == 6
        assert RunEvent.objects.filter(run=run).count() == 6

        run.refresh_from_db()
        assert run.status == RunStatus.FINISHED
        assert run.total_tokens == 400
        assert run.total_cost_usd == Decimal("0.40")
