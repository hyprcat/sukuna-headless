"""Tests for capability token minter (Phase 8E)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from apps.core.exceptions import Conflict
from apps.runs.services.capability_token import (
    CapabilityTokenFormat,
    mint_capability_token,
    refresh_capability_token,
)
from apps.runs.tests.conftest import generate_ed25519_keypair, private_key_b64

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def _format() -> CapabilityTokenFormat:
    return CapabilityTokenFormat()


def _common_kwargs() -> MutableMapping[str, object]:
    return {
        "run_id": uuid.uuid4(),
        "sandbox_id": "sbx-test-123",
        "workspace_id": 1,
        "end_user_id": 20,
        "conversation_id": uuid.uuid4(),
        "scopes": ["stream:read", "hitl:respond"],
    }


def _mint_patched(private_key, **kwargs):
    with patch("config.runtime.runtime") as mock_rt:
        mock_rt.midsphere_jwt_key_id = "jwt-k1"
        mock_rt.midsphere_jwt_private_key = private_key_b64(private_key)
        mock_rt.capability_token_ttl_seconds = 1800
        return mint_capability_token(**kwargs)


class TestMintCapabilityToken:
    def test_mint_returns_token_and_expiry(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        token, expires_at = _mint_patched(private_key, **_common_kwargs())

        assert isinstance(token, str)
        assert expires_at > datetime.now(UTC)
        assert expires_at < datetime.now(UTC) + timedelta(seconds=1900)

    def test_decode_verify_roundtrip(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        kwargs = _common_kwargs()
        token, _ = _mint_patched(private_key, **kwargs)

        decoded = pyjwt.decode(
            token,
            private_key.public_key(),
            algorithms=["EdDSA"],
            audience=_format().audience,
            issuer=_format().issuer,
        )
        assert decoded["sub"] == str(kwargs["run_id"])
        assert decoded["sandbox_id"] == kwargs["sandbox_id"]
        assert decoded["workspace_id"] == str(kwargs["workspace_id"])
        assert decoded["end_user_id"] == str(kwargs["end_user_id"])
        assert decoded["conversation_id"] == str(kwargs["conversation_id"])
        assert decoded["scope"] == ["stream:read", "hitl:respond"]
        assert decoded["iss"] == _format().issuer
        assert decoded["aud"] == _format().audience

    def test_header_contains_kid(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        token, _ = _mint_patched(private_key, **_common_kwargs())

        header = pyjwt.get_unverified_header(token)
        assert header["kid"] == "jwt-k1"
        assert header["alg"] == "EdDSA"

    def test_all_required_claims_present(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        token, _ = _mint_patched(private_key, **_common_kwargs())

        decoded = pyjwt.decode(
            token,
            private_key.public_key(),
            algorithms=["EdDSA"],
            audience=_format().audience,
            issuer=_format().issuer,
        )
        required = {
            "exp",
            "iat",
            "iss",
            "aud",
            "sub",
            "sandbox_id",
            "scope",
            "workspace_id",
            "end_user_id",
            "conversation_id",
            "jti",
        }
        assert required <= set(decoded.keys())

    def test_scope_filtering(self) -> None:
        """Invalid scopes are silently filtered out."""
        private_key, _ = generate_ed25519_keypair()
        kwargs = _common_kwargs()
        kwargs["scopes"] = ["stream:read", "bogus:scope", "files:rw"]
        token, _ = _mint_patched(private_key, **kwargs)

        decoded = pyjwt.decode(
            token,
            private_key.public_key(),
            algorithms=["EdDSA"],
            audience=_format().audience,
            issuer=_format().issuer,
        )
        assert decoded["scope"] == ["stream:read", "files:rw"]

    def test_no_valid_scopes_raises(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        kwargs = _common_kwargs()
        kwargs["scopes"] = ["bogus:scope"]
        with pytest.raises(ValueError, match="valid scope"):
            _mint_patched(private_key, **kwargs)

    def test_jti_uniqueness(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        kwargs = _common_kwargs()
        jtis = set()
        for _ in range(3):
            token, _ = _mint_patched(private_key, **kwargs)
            decoded = pyjwt.decode(
                token,
                private_key.public_key(),
                algorithms=["EdDSA"],
                audience=_format().audience,
                issuer=_format().issuer,
            )
            jtis.add(decoded["jti"])
        assert len(jtis) == 3

    def test_workspace_and_end_user_as_strings(self) -> None:
        """Sandbox expects workspace_id and end_user_id as strings."""
        private_key, _ = generate_ed25519_keypair()
        kwargs = _common_kwargs()
        kwargs["workspace_id"] = 42
        kwargs["end_user_id"] = 99
        token, _ = _mint_patched(private_key, **kwargs)

        decoded = pyjwt.decode(
            token,
            private_key.public_key(),
            algorithms=["EdDSA"],
            audience=_format().audience,
            issuer=_format().issuer,
        )
        assert decoded["workspace_id"] == "42"
        assert decoded["end_user_id"] == "99"

    def test_pem_key_format(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
        kwargs = _common_kwargs()
        with patch("config.runtime.runtime") as mock_rt:
            mock_rt.midsphere_jwt_key_id = "jwt-k1"
            mock_rt.midsphere_jwt_private_key = pem
            mock_rt.capability_token_ttl_seconds = 1800
            token, _ = mint_capability_token(**kwargs)

        decoded = pyjwt.decode(
            token,
            private_key.public_key(),
            algorithms=["EdDSA"],
            audience=_format().audience,
            issuer=_format().issuer,
        )
        assert decoded["iss"] == _format().issuer

    def test_valid_scopes_constant(self) -> None:
        expected = {"stream:read", "hitl:respond", "run:cancel", "files:rw", "mcp:manage"}
        assert expected == _format().valid_scopes


class TestRefreshCapabilityToken:
    def test_refresh_active_run(self) -> None:
        private_key, _ = generate_ed25519_keypair()
        kwargs = _common_kwargs()
        with patch("config.runtime.runtime") as mock_rt:
            mock_rt.midsphere_jwt_key_id = "jwt-k1"
            mock_rt.midsphere_jwt_private_key = private_key_b64(private_key)
            mock_rt.capability_token_ttl_seconds = 1800
            token, expires_at = refresh_capability_token(**kwargs, is_terminal=False)

        assert isinstance(token, str)
        assert expires_at > datetime.now(UTC)

    def test_refresh_terminal_run_raises(self) -> None:
        kwargs = _common_kwargs()
        with pytest.raises(Conflict, match="terminal"):
            refresh_capability_token(**kwargs, is_terminal=True)
