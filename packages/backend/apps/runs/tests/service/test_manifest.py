from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from apps.core.exceptions import InvalidInput
from apps.runs.factories import RunFactory, RunManifestRecordFactory
from apps.runs.models.records import RunManifestRecord
from apps.runs.services.manifest import (
    ManifestInput,
    ManifestKnowledge,
    ManifestLease,
    ManifestTool,
    SignedManifest,
    build_manifest,
    sign_manifest,
)
from apps.runs.tests.conftest import generate_ed25519_keypair, private_key_b64

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.django_db


def _make_input(**overrides) -> ManifestInput:
    defaults = {
        "run_id": uuid.uuid4(),
        "sandbox_id": "sbx-test-123",
        "workspace_id": 1,
        "agent_id": 10,
        "end_user_id": 20,
        "conversation_id": uuid.uuid4(),
        "prompt": "What is 2+2?",
        "system_prompt": "You are a helpful assistant.",
        "policy_block": "",
        "lease": ManifestLease(
            max_runtime_seconds=300,
            max_total_tokens=10000,
            max_cost_usd=Decimal("5.00"),
        ),
        "model_tier": "pro",
        "hitl_mode": "interactive",
        "tools": (),
        "knowledge": (),
        "callback_url": "https://api.midsphere.com/webhooks/sandbox/callbacks",
        "callback_auth": "hmac-secret-key-base64",
    }
    defaults.update(overrides)
    return ManifestInput(**defaults)


def _patch_runtime(**attrs):
    from config.runtime import runtime  # noqa: PLC0415

    return patch.object(runtime, "__class__", type("_", (runtime.__class__,), attrs))


def _build_manifest_patched(inp, **rt_overrides):
    defaults = {"midsphere_manifest_key_id": "k1", "manifest_expiry_seconds": 300}
    defaults.update(rt_overrides)
    with patch("config.runtime.runtime") as mock_rt:
        for k, v in defaults.items():
            setattr(mock_rt, k, v)
        return build_manifest(inp)


def _sign_manifest_patched(body, private_key):
    with patch("config.runtime.runtime") as mock_rt:
        mock_rt.midsphere_manifest_key_id = "k1"
        mock_rt.manifest_expiry_seconds = 300
        mock_rt.midsphere_manifest_private_key = private_key_b64(private_key)
        return sign_manifest(body)


class TestBuildManifest:
    def test_required_fields_present(self) -> None:
        inp = _make_input()
        body = _build_manifest_patched(inp, midsphere_manifest_key_id="key-1")

        assert body["manifest_version"] == 1
        assert body["run_id"] == str(inp.run_id)
        assert body["sandbox_id"] == inp.sandbox_id
        assert body["workspace_id"] == inp.workspace_id
        assert body["agent_id"] == inp.agent_id
        assert body["end_user_id"] == inp.end_user_id
        assert body["conversation_id"] == str(inp.conversation_id)
        assert body["prompt"] == inp.prompt
        assert body["system_prompt"] == inp.system_prompt
        assert body["policy_block"] == inp.policy_block
        assert body["model_tier"] == "pro"
        assert body["hitl_mode"] == "interactive"
        assert body["callback_url"] == inp.callback_url
        assert body["callback_auth"] == inp.callback_auth
        assert body["signing_key_id"] == "key-1"

    def test_lease_serialization(self) -> None:
        inp = _make_input()
        body = _build_manifest_patched(inp)

        assert body["lease"]["max_runtime_seconds"] == 300
        assert body["lease"]["max_total_tokens"] == 10000
        assert body["lease"]["max_cost_usd"] == "5.00"

    def test_tools_serialization(self) -> None:
        tool = ManifestTool(
            id=1,
            name="search",
            description="Search the web",
            parameters_schema={"type": "object"},
            execution_endpoint="https://tools.example.com/search",
            is_sensitive=True,
        )
        inp = _make_input(tools=(tool,))
        body = _build_manifest_patched(inp)

        assert len(body["tools"]) == 1
        assert body["tools"][0]["id"] == 1
        assert body["tools"][0]["name"] == "search"
        assert body["tools"][0]["is_sensitive"] is True
        assert body["tools"][0]["execution_endpoint"] == "https://tools.example.com/search"

    def test_knowledge_serialization(self) -> None:
        kb = ManifestKnowledge(
            id=5, name="docs", kind="document", source="https://storage/docs.pdf"
        )
        inp = _make_input(knowledge=(kb,))
        body = _build_manifest_patched(inp)

        assert len(body["knowledge"]) == 1
        assert body["knowledge"][0]["kind"] == "document"

    def test_expires_at_set(self) -> None:
        inp = _make_input()
        body = _build_manifest_patched(inp, manifest_expiry_seconds=600)

        expires = datetime.fromisoformat(body["expires_at"])
        assert expires > datetime.now(UTC)
        assert expires < datetime.now(UTC) + timedelta(seconds=700)


class TestSignManifest:
    def test_sign_verify_roundtrip(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        inp = _make_input()
        body = _build_manifest_patched(inp)
        result = _sign_manifest_patched(body, private_key)

        assert isinstance(result, SignedManifest)
        assert result.manifest_id == body["manifest_id"]
        assert len(result.manifest_hash) == 64

        parsed = json.loads(result.body)
        assert "signature" in parsed

        sig_bytes = base64.b64decode(parsed["signature"])
        body_without_sig = {k: v for k, v in parsed.items() if k != "signature"}
        canonical = json.dumps(body_without_sig, sort_keys=True, separators=(",", ":")).encode()
        private_key.public_key().verify(sig_bytes, canonical)

    def test_oversized_manifest_rejected(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        inp = _make_input(prompt="x" * (1024 * 1024 + 1))
        body = _build_manifest_patched(inp)
        with pytest.raises(InvalidInput, match="1 MB"):
            _sign_manifest_patched(body, private_key)

    def test_signed_body_over_size_limit_rejected(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        body = _build_manifest_patched(_make_input(prompt=""))
        body["prompt"] = "x" * _prompt_size_for_signature_overflow(body)

        with pytest.raises(InvalidInput, match="1 MB"):
            _sign_manifest_patched(body, private_key)

    def test_manifest_hash_matches_body(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        inp = _make_input()
        body = _build_manifest_patched(inp)
        result = _sign_manifest_patched(body, private_key)

        assert result.manifest_hash == RunManifestRecord.compute_manifest_hash(result.body)

    def test_field_completeness(self) -> None:
        """Signed manifest contains all fields the sandbox RunManifest expects."""
        private_key, _ = generate_ed25519_keypair()
        tool = ManifestTool(
            id=1,
            name="t",
            description="d",
            parameters_schema={},
            execution_endpoint="https://e.co/t",
            is_sensitive=False,
        )
        kb = ManifestKnowledge(id=2, name="k", kind="document", source="https://s.co/k")
        inp = _make_input(tools=(tool,), knowledge=(kb,))
        body = _build_manifest_patched(inp)
        result = _sign_manifest_patched(body, private_key)

        parsed = json.loads(result.body)
        expected_keys = {
            "manifest_version",
            "manifest_id",
            "signing_key_id",
            "signature",
            "expires_at",
            "run_id",
            "sandbox_id",
            "workspace_id",
            "agent_id",
            "end_user_id",
            "conversation_id",
            "prompt",
            "system_prompt",
            "policy_block",
            "lease",
            "model_tier",
            "hitl_mode",
            "tools",
            "knowledge",
            "callback_url",
            "callback_auth",
        }
        assert set(parsed.keys()) == expected_keys

    def test_pem_private_key_loading(self) -> None:
        """Private key in PEM format works for signing."""
        private_key, _ = generate_ed25519_keypair()
        pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()

        inp = _make_input()
        body = _build_manifest_patched(inp)
        with patch("config.runtime.runtime") as mock_rt:
            mock_rt.midsphere_manifest_key_id = "k1"
            mock_rt.manifest_expiry_seconds = 300
            mock_rt.midsphere_manifest_private_key = pem
            result = sign_manifest(body)

        assert len(result.body) > 0


def _prompt_size_for_signature_overflow(body: Mapping[str, object]) -> int:
    probe = dict(body)
    probe["prompt"] = ""
    base_size = len(json.dumps(probe, sort_keys=True, separators=(",", ":")).encode())
    return 1024 * 1024 - base_size - 1


# -- RunManifestRecord model tests --


class TestRunManifestRecord:
    def test_created_with_defaults(self) -> None:
        record = RunManifestRecordFactory()
        assert record.manifest_id is not None
        assert record.schema_version == 1
        assert record.signing_key_id == "test-key-001"
        assert len(record.manifest_hash) == 64
        assert record.created_at is not None

    def test_encrypt_decrypt_round_trip(self) -> None:
        raw_key = os.urandom(32)
        encrypted = RunManifestRecord.encrypt_callback_auth(raw_key)
        assert encrypted != raw_key
        record = RunManifestRecordFactory(callback_auth_encrypted=encrypted)
        decrypted = record.decrypt_callback_auth()
        assert decrypted == raw_key

    def test_decrypt_returns_original_bytes(self) -> None:
        raw_key = b"my-secret-hmac-key-for-callbacks"
        encrypted = RunManifestRecord.encrypt_callback_auth(raw_key)
        record = RunManifestRecordFactory(callback_auth_encrypted=encrypted)
        assert record.decrypt_callback_auth() == raw_key

    def test_multiple_manifests_for_same_run(self) -> None:
        run = RunFactory(running=True)
        r1 = RunManifestRecordFactory(run=run)
        r2 = RunManifestRecordFactory(run=run)
        assert r1.manifest_id != r2.manifest_id
        assert run.manifest_records.count() == 2
