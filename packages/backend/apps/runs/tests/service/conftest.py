"""Callback-specific test helpers shared across callback test modules."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from django.utils import timezone

from apps.billing.factories import CreditWalletFactory
from apps.runs.factories import RunFactory, RunManifestRecordFactory
from config.runtime import runtime

if TYPE_CHECKING:
    from apps.runs.models.records import RunManifestRecord
    from apps.runs.models.run import Run


def make_callback_auth() -> tuple[bytes, bytes]:
    raw_key = os.urandom(32)
    f = Fernet(runtime.fernet_encryption_key.encode())
    encrypted = f.encrypt(raw_key)
    return raw_key, encrypted


def sign_batch(envelope: dict, callback_auth: bytes) -> str:
    without_sig = {k: v for k, v in envelope.items() if k != "signature"}
    canonical = json.dumps(without_sig, sort_keys=True, separators=(",", ":")).encode()
    # The manifest carries callback_auth as hex and the sandbox signs with that
    # string's bytes — match it so verification succeeds.
    key = callback_auth.hex().encode()
    return hmac_mod.new(key, canonical, hashlib.sha256).hexdigest()


def make_event(
    seq: int,
    event_type: str,
    payload: dict | None = None,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "sequence_no": seq,
        "emitted_at": timezone.now().isoformat(),
        "event_type": event_type,
        "payload": payload or {},
    }


def make_batch(
    run: Run,
    manifest_record: RunManifestRecord,
    events: list[dict],
    callback_auth: bytes,
) -> bytes:
    envelope = {
        "manifest_id": str(manifest_record.manifest_id),
        "run_id": str(run.run_uid),
        "sandbox_id": manifest_record.sandbox_id,
        "batch_id": str(uuid.uuid4()),
        "schema_version": 1,
        "sent_at": timezone.now().isoformat(),
        "events": events,
        "signature": "",
    }
    envelope["signature"] = sign_batch(envelope, callback_auth)
    return json.dumps(envelope).encode()


def started_payload(sandbox_id: str = "sbx-1") -> dict:
    return {"model_tier": "free", "sandbox_id": sandbox_id}


def usage_payload(tokens: int = 100, cost: str = "0.01") -> dict:
    return {
        "runtime_seconds": 5,
        "total_tokens": tokens,
        "cost_usd": cost,
        "tool_calls_count": 0,
    }


def final_usage(tokens: int = 500, cost: str = "0.50") -> dict:
    return {"runtime_seconds": 30, "total_tokens": tokens, "cost_usd": cost}


def setup_run_with_manifest():
    raw_key, encrypted = make_callback_auth()
    run = RunFactory(running=True)
    wallet = CreditWalletFactory(workspace=run.workspace)
    wallet.record_dodo_credit_grant(
        Decimal("100.00"),
        dodo_payment_id=f"setup-{uuid.uuid4().hex}",
    )
    record = RunManifestRecordFactory(
        run=run,
        callback_auth_encrypted=encrypted,
    )
    return run, record, raw_key, wallet
