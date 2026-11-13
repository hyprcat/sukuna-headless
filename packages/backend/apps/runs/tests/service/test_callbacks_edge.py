"""Tests for callback validation, deduplication, and HTTP endpoint."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from django.test import Client, TestCase
from django.utils import timezone

from apps.billing.factories import BillingHoldFactory
from apps.core.exceptions import NotFound
from apps.runs.factories import RunFactory, RunManifestRecordFactory
from apps.runs.models.records import RunEvent
from apps.runs.schemas.events import RunStatus
from apps.runs.services.callbacks import InvalidCallback, verify_and_ingest
from apps.runs.tests.service.conftest import (
    final_usage,
    make_batch,
    make_callback_auth,
    make_event,
    setup_run_with_manifest,
    sign_batch,
    started_payload,
)

pytestmark = pytest.mark.django_db


class TestHMACVerification(TestCase):
    def test_invalid_hmac_rejected(self):
        run, record, key, _ = setup_run_with_manifest()
        events = [make_event(1, "run_started", started_payload())]
        body = make_batch(run, record, events, key)
        tampered = json.loads(body)
        tampered["signature"] = "deadbeef" * 8
        with pytest.raises(InvalidCallback, match="HMAC"):
            verify_and_ingest(json.dumps(tampered).encode())

    def test_missing_signature_rejected(self):
        run, record, _key, _ = setup_run_with_manifest()
        envelope = {
            "manifest_id": str(record.manifest_id),
            "run_id": str(run.run_uid),
            "sandbox_id": record.sandbox_id,
            "batch_id": str(uuid.uuid4()),
            "schema_version": 1,
            "sent_at": timezone.now().isoformat(),
            "events": [make_event(1, "run_started", {})],
        }
        with pytest.raises(InvalidCallback, match="signature"):
            verify_and_ingest(json.dumps(envelope).encode())

    def test_wrong_sandbox_id_rejected(self):
        run, record, key, _ = setup_run_with_manifest()
        envelope = json.loads(make_batch(run, record, [make_event(1, "run_started", {})], key))
        envelope["sandbox_id"] = "different-sandbox"
        envelope["signature"] = sign_batch(envelope, key)
        with pytest.raises(InvalidCallback, match="sandbox_id"):
            verify_and_ingest(json.dumps(envelope).encode())


class TestDuplicateHandling(TestCase):
    def test_duplicate_callback_event_id_skipped(self):
        run, record, key, _ = setup_run_with_manifest()
        event = make_event(1, "run_started", started_payload())
        body = make_batch(run, record, [event], key)
        result1 = verify_and_ingest(body)
        assert result1["acked_through"] == 1
        assert RunEvent.objects.filter(run=run).count() == 1

        body2 = make_batch(run, record, [event], key)
        result2 = verify_and_ingest(body2)
        assert result2["acked_through"] == 1
        assert RunEvent.objects.filter(run=run).count() == 1

    def test_callback_event_id_reuse_rejected(self):
        other_run = RunFactory(running=True)
        existing_event_id = uuid.uuid4()
        RunEvent.objects.create(
            run=other_run,
            sequence_no=1,
            event_type="run_started",
            payload={},
            callback_event_id=existing_event_id,
        )
        run, record, key, _ = setup_run_with_manifest()
        event = make_event(1, "run_started", started_payload())
        event["event_id"] = str(existing_event_id)
        body = make_batch(run, record, [event], key)

        with pytest.raises(InvalidCallback, match="conflicts"):
            verify_and_ingest(body)

        run.refresh_from_db()
        assert run.last_projected_sequence == 0
        assert RunEvent.objects.filter(run=run).count() == 0

    def test_sequence_conflict_rejected(self):
        run, record, key, _ = setup_run_with_manifest()
        RunEvent.objects.create(
            run=run,
            sequence_no=1,
            event_type="step",
            payload={"output": "stored"},
            callback_event_id=uuid.uuid4(),
        )
        event = make_event(1, "run_started", started_payload("tampered"))
        body = make_batch(run, record, [event], key)

        with pytest.raises(InvalidCallback, match="conflicts"):
            verify_and_ingest(body)

        run.refresh_from_db()
        assert run.last_projected_sequence == 0
        assert run.sandbox_id != "tampered"

    def test_double_terminal_rejected(self):
        run, record, key, wallet = setup_run_with_manifest()
        BillingHoldFactory(run=run, wallet=wallet, amount_reserved_usd=Decimal("10.00"))
        events = [
            make_event(1, "run_started", started_payload()),
            make_event(
                2,
                "run_completed",
                {"final_usage": final_usage(500, "0.50"), "summary": "Done"},
            ),
        ]
        body = make_batch(run, record, events, key)
        verify_and_ingest(body)

        second_terminal = [
            make_event(
                3,
                "run_failed",
                {
                    "error_code": "tool_failed",
                    "message": "Late failure",
                    "final_usage": final_usage(510, "0.55"),
                },
            ),
        ]
        body2 = make_batch(run, record, second_terminal, key)
        result = verify_and_ingest(body2)
        assert result["acked_through"] == 2

        run.refresh_from_db()
        assert run.status == RunStatus.FINISHED


class TestSequenceGaps(TestCase):
    def test_gap_stops_processing(self):
        run, record, key, _ = setup_run_with_manifest()
        events = [
            make_event(1, "run_started", started_payload()),
            make_event(3, "usage_checkpoint"),
        ]
        body = make_batch(run, record, events, key)
        result = verify_and_ingest(body)

        assert result["acked_through"] == 1
        assert result.get("expected_sequence") == 2
        assert RunEvent.objects.filter(run=run).count() == 1


class TestManifestLookup(TestCase):
    def test_unknown_manifest_id_returns_404(self):
        _raw_key, encrypted = make_callback_auth()
        run = RunFactory(running=True)
        RunManifestRecordFactory(run=run, callback_auth_encrypted=encrypted)
        envelope = {
            "manifest_id": str(uuid.uuid4()),
            "run_id": str(run.run_uid),
            "sandbox_id": "sbx-1",
            "batch_id": str(uuid.uuid4()),
            "schema_version": 1,
            "sent_at": timezone.now().isoformat(),
            "events": [make_event(1, "run_started", {})],
            "signature": "placeholder",
        }
        with pytest.raises(NotFound):
            verify_and_ingest(json.dumps(envelope).encode())


class TestCallbackEndpoint(TestCase):
    def setUp(self):
        self.client = Client()

    def test_valid_batch_returns_200(self):
        run, record, key, _ = setup_run_with_manifest()
        events = [make_event(1, "run_started", started_payload())]
        body = make_batch(run, record, events, key)
        response = self.client.post(
            "/webhooks/sandbox/callbacks",
            data=body,
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["acked_through"] == 1
        assert data["status"] == "ok"

    def test_invalid_hmac_returns_400(self):
        run, record, key, _ = setup_run_with_manifest()
        events = [make_event(1, "run_started", started_payload())]
        body = make_batch(run, record, events, key)
        tampered = json.loads(body)
        tampered["signature"] = "bad" * 16
        response = self.client.post(
            "/webhooks/sandbox/callbacks",
            data=json.dumps(tampered),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_manifest_returns_404(self):
        envelope = {
            "manifest_id": str(uuid.uuid4()),
            "run_id": str(uuid.uuid4()),
            "sandbox_id": "sbx-1",
            "batch_id": str(uuid.uuid4()),
            "schema_version": 1,
            "sent_at": timezone.now().isoformat(),
            "events": [make_event(1, "run_started", {})],
            "signature": "placeholder",
        }
        response = self.client.post(
            "/webhooks/sandbox/callbacks",
            data=json.dumps(envelope),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_malformed_json_returns_400(self):
        response = self.client.post(
            "/webhooks/sandbox/callbacks",
            data=b"not json {{{",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_invalid_events_shape_returns_400(self):
        run, record, key, _ = setup_run_with_manifest()
        envelope = json.loads(make_batch(run, record, [make_event(1, "run_started")], key))
        envelope["events"] = {"sequence_no": 1}
        envelope["signature"] = sign_batch(envelope, key)
        response = self.client.post(
            "/webhooks/sandbox/callbacks",
            data=json.dumps(envelope),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_get_method_not_allowed(self):
        response = self.client.get("/webhooks/sandbox/callbacks")
        assert response.status_code == 405
