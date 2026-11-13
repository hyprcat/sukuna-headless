"""Callback batch ingestion from sandbox runtime.

Receives signed callback batches, verifies HMAC-SHA256, persists RunEvent
rows, projects state-affecting events onto the Run, and settles billing
holds on terminal events.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

import structlog
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.core.events import record_event
from apps.core.exceptions import NotFound
from apps.runs.models.records import RunEvent, RunManifestRecord
from apps.runs.models.run import Run
from apps.runs.models.sandbox_instance import SandboxInstance, SandboxState
from apps.runs.schemas.events import RunCancelled, RunFailed, RunFinished, UsageEvent
from apps.runs.services.event_mapping import map_to_usage_event

_log = structlog.get_logger(__name__)


class InvalidCallback(Exception):
    """Raised for structurally invalid or untrusted callback batches."""


def verify_and_ingest(raw_body: bytes) -> dict[str, Any]:
    """Entry point: parse envelope, verify HMAC, ingest events."""
    try:
        envelope = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidCallback("Malformed JSON body.") from exc

    manifest_id = _require_uuid(envelope, "manifest_id")
    run_id = _require_uuid(envelope, "run_id")
    signature = envelope.get("signature", "")
    if not signature:
        raise InvalidCallback("Missing signature.")

    record = _load_manifest_record(manifest_id, run_id)
    _verify_hmac(envelope, record)
    _guard_envelope_matches_record(envelope, record)
    return _ingest_batch(envelope, record)


def _require_uuid(data: dict[str, Any], key: str) -> UUID:
    raw = data.get(key)
    if not raw:
        raise InvalidCallback(f"Missing {key}.")
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise InvalidCallback(f"Invalid {key}.") from exc


def _load_manifest_record(manifest_id: UUID, run_id: UUID) -> RunManifestRecord:
    try:
        record = RunManifestRecord.objects.select_related("run").get(
            manifest_id=manifest_id,
        )
    except RunManifestRecord.DoesNotExist as exc:
        raise NotFound(f"Unknown manifest_id {manifest_id}.") from exc
    if record.run.run_uid != run_id:
        raise InvalidCallback("run_id does not match manifest.")
    return record


def _verify_hmac(envelope: dict[str, Any], record: RunManifestRecord) -> None:
    # The manifest carries callback_auth as a hex string (run_records: ``.hex()``),
    # and the sandbox signs with that string's UTF-8 bytes — so verify against the
    # same hex form, not the raw decrypted bytes.
    callback_auth = record.decrypt_callback_auth().hex().encode()
    without_sig = {k: v for k, v in envelope.items() if k != "signature"}
    canonical = json.dumps(without_sig, sort_keys=True, separators=(",", ":")).encode()
    expected = hmac.new(callback_auth, canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, envelope["signature"]):
        raise InvalidCallback("HMAC verification failed.")


def _guard_envelope_matches_record(
    envelope: dict[str, Any],
    record: RunManifestRecord,
) -> None:
    if str(envelope.get("sandbox_id", "")) != record.sandbox_id:
        raise InvalidCallback("sandbox_id does not match manifest.")


@transaction.atomic
def _ingest_batch(envelope: dict[str, Any], record: RunManifestRecord) -> dict[str, Any]:
    run = Run.objects.select_for_update().get(pk=record.run_id)
    if run.is_terminal:
        return {"acked_through": run.last_projected_sequence, "status": "ok"}

    batch_id = _require_uuid(envelope, "batch_id")
    events = envelope.get("events")
    if not isinstance(events, list) or not events:
        raise InvalidCallback("Callback batch must include events.")

    sorted_events = sorted(events, key=lambda e: e.get("sequence_no", 0))
    acked_through, gap, terminal = _process_events(run, sorted_events, batch_id)

    _persist_run(run, acked_through)
    if terminal is not None:
        _settle_terminal(run, terminal)
        _release_sandbox(run)

    response: dict[str, Any] = {"acked_through": acked_through, "status": "ok"}
    if gap:
        response["expected_sequence"] = acked_through + 1
    return response


def _process_events(
    run: Run,
    sorted_events: list[dict[str, Any]],
    batch_id: UUID,
) -> tuple[int, bool, UsageEvent | None]:
    acked_through = run.last_projected_sequence
    terminal_event: UsageEvent | None = None

    # Callback sequence_no is the sandbox's GLOBAL runtime-event counter, and only
    # a subset of events become callbacks — so callback sequences are sparse (e.g.
    # 1, 7, 18), not contiguous. Apply events in monotonic order; ``seq <= acked``
    # skips already-applied ones (idempotent, also enforced by a UNIQUE constraint).
    for event_data in sorted_events:
        seq = event_data.get("sequence_no", 0)
        if seq < 1 or seq <= acked_through:
            continue
        if run.is_terminal:
            return acked_through, False, terminal_event

        _write_event_row(run, event_data, batch_id)
        terminal_event = _project_if_needed(run, event_data) or terminal_event
        acked_through = seq

    return acked_through, False, terminal_event


def _project_if_needed(run: Run, event_data: dict[str, Any]) -> UsageEvent | None:
    if run.is_terminal:
        return None
    usage = map_to_usage_event(event_data, run.run_uid)
    if not usage:
        return None
    run._project_event(usage)
    if isinstance(usage, (RunFinished, RunFailed, RunCancelled)):
        return usage
    return None


def _write_event_row(run: Run, event_data: dict[str, Any], batch_id: UUID) -> None:
    event_id = _require_uuid(event_data, "event_id")
    try:
        with transaction.atomic():
            RunEvent.objects.create(
                run=run,
                sequence_no=event_data["sequence_no"],
                event_type=event_data.get("event_type", "unknown"),
                payload=event_data.get("payload", {}),
                callback_event_id=event_id,
                batch_id=batch_id,
            )
    except IntegrityError as exc:
        raise InvalidCallback("Callback event conflicts with stored event log.") from exc


def _persist_run(run: Run, acked_through: int) -> None:
    run.last_callback_at = timezone.now()
    run.last_projected_sequence = acked_through
    run.save(
        update_fields=[
            "status",
            "state_json",
            "total_tokens",
            "total_cost_usd",
            "started_at",
            "finished_at",
            "sandbox_id",
            "error_message",
            "last_callback_at",
            "last_projected_sequence",
            "updated_at",
        ],
    )


def _settle_terminal(run: Run, event: UsageEvent) -> None:
    try:
        hold = BillingHold.objects.get(run=run)
    except BillingHold.DoesNotExist:
        _log.warning("callback_no_hold", run_uid=str(run.run_uid))
        return

    if hold.status != HoldStatus.ACTIVE:
        return

    if isinstance(event, RunFailed):
        hold.release()
        _log.info("callback_hold_released", run_uid=str(run.run_uid))
    else:
        actual_cost = min(run.total_cost_usd, hold.amount_reserved_usd)
        hold.settle(actual_cost)
        _log.info("callback_hold_settled", run_uid=str(run.run_uid), cost=str(actual_cost))

    record_event(
        "run_billing_settled",
        distinct_id=str(run.workspace_id),
        properties={
            "run_id": str(run.run_uid),
            "hold_status": hold.status,
            "cost_usd": str(run.total_cost_usd),
        },
    )


def _release_sandbox(run: Run) -> None:
    instances = SandboxInstance.objects.filter(
        current_run=run,
        sandbox_state=SandboxState.RUNNING,
    )
    for instance in instances:
        instance.mark_paused()
        _log.info("callback_sandbox_paused", sandbox_id=instance.sandbox_id)
