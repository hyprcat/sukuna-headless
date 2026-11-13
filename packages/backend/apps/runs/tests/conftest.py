"""Shared test helpers for runs app tests."""

from __future__ import annotations

import base64
import contextlib
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from apps.agents.factories import AgentFactory
from apps.api_keys.principals import ApiKeyPrincipal
from apps.billing.factories import CreditWalletFactory
from apps.end_users.factories import EndUserFactory
from integrations.e2b import SandboxHandle


def generate_ed25519_keypair() -> tuple[Ed25519PrivateKey, bytes]:
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key().public_bytes_raw()


def private_key_b64(private_key: Ed25519PrivateKey) -> str:
    return base64.b64encode(private_key.private_bytes_raw()).decode()


def session_ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: True)
    principal = SimpleNamespace(
        workspace_id=workspace.pk,
        member=member,
        scopes=frozenset(),
    )
    return SimpleNamespace(workspace=workspace, principal=principal)


def denied_session_ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: False)
    principal = SimpleNamespace(
        workspace_id=workspace.pk,
        member=member,
        scopes=frozenset(),
    )
    return SimpleNamespace(workspace=workspace, principal=principal)


def api_key_ctx(
    workspace: object,
    scopes: frozenset[str],
) -> SimpleNamespace:
    api_key = SimpleNamespace(workspace_id=workspace.pk)
    principal = ApiKeyPrincipal(api_key=api_key, scopes=scopes)  # type: ignore[arg-type]
    return SimpleNamespace(workspace=workspace, principal=principal)


def setup_run_env(
    *,
    credits: int = 100,
    wallet_balance: Decimal | None = Decimal("100.00"),
):
    eu = EndUserFactory(free_tier=True, profile__credits=credits)
    ws = eu.workspace
    agent = AgentFactory(workspace=ws)
    wallet = CreditWalletFactory(workspace=ws)
    if wallet_balance and wallet_balance > 0:
        wallet.record_dodo_credit_grant(
            wallet_balance,
            dodo_payment_id=f"seed-{uuid.uuid4().hex}",
        )
    return ws, agent, eu, wallet


def sandbox_handle(sandbox_id: str = "sbx-test-001") -> SandboxHandle:
    return SandboxHandle(
        sandbox_id=sandbox_id,
        sandbox_url=f"https://{sandbox_id}.e2b.app",
    )


@contextlib.contextmanager
def patched_signing():
    manifest_b64 = private_key_b64(Ed25519PrivateKey.generate())
    jwt_b64 = private_key_b64(Ed25519PrivateKey.generate())
    with (
        patch("config.runtime.runtime.midsphere_manifest_private_key", manifest_b64),
        patch("config.runtime.runtime.midsphere_manifest_key_id", "test-manifest-key"),
        patch("config.runtime.runtime.midsphere_jwt_private_key", jwt_b64),
        patch("config.runtime.runtime.midsphere_jwt_key_id", "test-jwt-key"),
        patch("config.runtime.runtime.backend_public_url", "https://api.test.midsphere.com"),
    ):
        yield


@contextlib.contextmanager
def patched_e2b_env(sandbox_id: str = "sbx-test-001"):
    handle = sandbox_handle(sandbox_id)
    _e2b = "integrations.e2b"
    with (
        patched_signing(),
        patch(f"{_e2b}.spawn_sandbox", new_callable=AsyncMock, return_value=handle) as m_spawn,
        patch(f"{_e2b}.resume_sandbox", new_callable=AsyncMock, return_value=handle) as m_resume,
        patch(f"{_e2b}.pause_sandbox", new_callable=AsyncMock) as m_pause,
        patch(f"{_e2b}.terminate_sandbox", new_callable=AsyncMock) as m_term,
        patch(f"{_e2b}.post_manifest", new_callable=AsyncMock) as m_post,
        patch(f"{_e2b}.set_sandbox_timeout", new_callable=AsyncMock) as m_timeout,
    ):
        yield {
            "spawn": m_spawn,
            "resume": m_resume,
            "pause": m_pause,
            "terminate": m_term,
            "post_manifest": m_post,
            "set_timeout": m_timeout,
        }
