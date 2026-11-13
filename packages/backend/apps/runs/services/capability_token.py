"""Mint and refresh EdDSA capability JWTs for sandbox authentication."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel, ConfigDict, Field

from apps.core.exceptions import Conflict


class CapabilityTokenFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    issuer: str = "midsphere-backend"
    audience: str = "midsphere-sandbox"
    algorithm: str = "EdDSA"
    valid_scopes: frozenset[str] = Field(
        default=frozenset({"stream:read", "hitl:respond", "run:cancel", "files:rw", "mcp:manage"})
    )


class CapabilityTokenClaims(BaseModel):
    model_config = ConfigDict(frozen=True)

    iss: str
    aud: str
    sub: str
    sandbox_id: str
    workspace_id: str
    end_user_id: str
    conversation_id: str
    scope: list[str]
    exp: int
    iat: int
    jti: str


def mint_capability_token(
    *,
    run_id: uuid.UUID,
    sandbox_id: str,
    workspace_id: int,
    end_user_id: int,
    conversation_id: uuid.UUID,
    scopes: list[str],
) -> tuple[str, datetime]:
    """Create a signed capability JWT for SDK-sandbox auth."""
    from config.runtime import runtime  # noqa: PLC0415

    fmt = CapabilityTokenFormat()
    filtered = _valid_scopes(scopes, fmt)
    if not filtered:
        raise ValueError("At least one valid scope is required.")
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=runtime.capability_token_ttl_seconds)
    claims = _build_claims(
        run_id, sandbox_id, workspace_id, end_user_id, conversation_id, filtered, now, expires_at
    )
    token = _sign_jwt(claims, runtime.midsphere_jwt_private_key, runtime.midsphere_jwt_key_id, fmt)
    return token, expires_at


def _valid_scopes(scopes: list[str], fmt: CapabilityTokenFormat) -> list[str]:
    return [s for s in scopes if s in fmt.valid_scopes]


def refresh_capability_token(
    *,
    run_id: uuid.UUID,
    sandbox_id: str,
    workspace_id: int,
    end_user_id: int,
    conversation_id: uuid.UUID,
    is_terminal: bool,
    scopes: list[str],
) -> tuple[str, datetime]:
    """Re-validate run state and mint a fresh capability JWT."""
    if is_terminal:
        raise Conflict("Cannot refresh token for a terminal run.")
    return mint_capability_token(
        run_id=run_id,
        sandbox_id=sandbox_id,
        workspace_id=workspace_id,
        end_user_id=end_user_id,
        conversation_id=conversation_id,
        scopes=scopes,
    )


def _build_claims(
    run_id: uuid.UUID,
    sandbox_id: str,
    workspace_id: int,
    end_user_id: int,
    conversation_id: uuid.UUID,
    scopes: list[str],
    now: datetime,
    expires_at: datetime,
) -> CapabilityTokenClaims:
    fmt = CapabilityTokenFormat()
    return CapabilityTokenClaims(
        iss=fmt.issuer,
        aud=fmt.audience,
        sub=str(run_id),
        sandbox_id=sandbox_id,
        workspace_id=str(workspace_id),
        end_user_id=str(end_user_id),
        conversation_id=str(conversation_id),
        scope=scopes,
        exp=int(expires_at.timestamp()),
        iat=int(now.timestamp()),
        jti=str(uuid.uuid4()),
    )


def _sign_jwt(
    payload: CapabilityTokenClaims, key_text: str, kid: str, fmt: CapabilityTokenFormat
) -> str:
    from apps.core.crypto import load_ed25519_private_key  # noqa: PLC0415

    private_key = load_ed25519_private_key(key_text)
    return jwt.encode(
        payload.model_dump(), private_key, algorithm=fmt.algorithm, headers={"kid": kid}
    )
