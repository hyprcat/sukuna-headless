"""Build and sign RunManifest payloads for sandbox execution."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal

from apps.core.exceptions import InvalidInput


class SignedManifest(NamedTuple):
    body: bytes
    manifest_id: str
    manifest_hash: str


class ManifestSigningFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_manifest_bytes: int = Field(default=1024 * 1024, gt=0)


@dataclass(frozen=True, slots=True)
class ManifestTool:
    id: int
    name: str
    description: str
    parameters_schema: dict[str, object]
    execution_endpoint: str
    is_sensitive: bool


@dataclass(frozen=True, slots=True)
class ManifestKnowledge:
    id: int
    name: str
    kind: str
    source: str


@dataclass(frozen=True, slots=True)
class ManifestLease:
    max_runtime_seconds: int
    max_total_tokens: int
    max_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class ManifestInput:
    run_id: uuid.UUID
    sandbox_id: str
    workspace_id: int
    agent_id: int
    end_user_id: int
    conversation_id: uuid.UUID
    prompt: str
    system_prompt: str
    policy_block: str
    lease: ManifestLease
    model_tier: str
    hitl_mode: str
    tools: tuple[ManifestTool, ...]
    knowledge: tuple[ManifestKnowledge, ...]
    callback_url: str
    callback_auth: str


def build_manifest(inp: ManifestInput) -> Mapping[str, object]:
    """Assemble a RunManifest dict matching the sandbox's schema."""
    from config.runtime import runtime  # noqa: PLC0415

    now = datetime.now(UTC)
    expires = now + timedelta(seconds=runtime.manifest_expiry_seconds)
    body = dict(_manifest_envelope(runtime.midsphere_manifest_key_id, expires))
    body.update(_manifest_identity(inp))
    body.update(_manifest_execution(inp))
    return body


def _manifest_envelope(key_id: str, expires: datetime) -> Mapping[str, object]:
    return {
        "manifest_version": 1,
        "manifest_id": str(uuid.uuid4()),
        "signing_key_id": key_id,
        "expires_at": expires.isoformat(),
    }


def _manifest_identity(inp: ManifestInput) -> Mapping[str, object]:
    return {
        "run_id": str(inp.run_id),
        "sandbox_id": inp.sandbox_id,
        "workspace_id": inp.workspace_id,
        "agent_id": inp.agent_id,
        "end_user_id": inp.end_user_id,
        "conversation_id": str(inp.conversation_id),
    }


def _manifest_execution(inp: ManifestInput) -> Mapping[str, object]:
    return {
        "prompt": inp.prompt,
        "system_prompt": inp.system_prompt,
        "policy_block": inp.policy_block,
        "lease": _serialize_lease(inp.lease),
        "model_tier": inp.model_tier,
        "hitl_mode": inp.hitl_mode,
        "tools": [asdict(t) for t in inp.tools],
        "knowledge": [asdict(k) for k in inp.knowledge],
        "callback_url": inp.callback_url,
        "callback_auth": inp.callback_auth,
    }


def _serialize_lease(lease: ManifestLease) -> Mapping[str, object]:
    return {
        "max_runtime_seconds": lease.max_runtime_seconds,
        "max_total_tokens": lease.max_total_tokens,
        "max_cost_usd": str(lease.max_cost_usd),
    }


def _canonical_bytes(body: Mapping[str, object]) -> bytes:
    stripped = {k: v for k, v in body.items() if k != "signature"}
    return json.dumps(stripped, sort_keys=True, separators=(",", ":")).encode()


def sign_manifest(manifest_body: Mapping[str, object]) -> SignedManifest:
    """Sign a manifest dict with Ed25519 and return the signed body bytes."""
    from config.runtime import runtime  # noqa: PLC0415

    canonical = _canonical_bytes(manifest_body)
    _ensure_manifest_size(canonical)
    signed_body = dict(manifest_body)
    signed_body["signature"] = _sign_bytes(canonical, runtime.midsphere_manifest_private_key)
    return _build_signed_result(signed_body)


def _sign_bytes(data: bytes, key_text: str) -> str:
    from apps.core.crypto import load_ed25519_private_key  # noqa: PLC0415

    private_key = load_ed25519_private_key(key_text)
    return base64.b64encode(private_key.sign(data)).decode()


def _build_signed_result(manifest_body: Mapping[str, object]) -> SignedManifest:
    from apps.runs.models.records import RunManifestRecord  # noqa: PLC0415

    body = json.dumps(manifest_body, sort_keys=True, separators=(",", ":")).encode()
    _ensure_manifest_size(body)
    return SignedManifest(
        body=body,
        manifest_id=str(manifest_body["manifest_id"]),
        manifest_hash=RunManifestRecord.compute_manifest_hash(body),
    )


def _ensure_manifest_size(body: bytes) -> None:
    if len(body) > ManifestSigningFormat().max_manifest_bytes:
        raise InvalidInput("Manifest exceeds 1 MB size limit.")
