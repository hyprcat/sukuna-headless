from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from django.core.cache import cache

from apps.accounts.models import User
from apps.accounts.schemas.config import AuthFlowConfig
from apps.accounts.services import auth_flows
from apps.accounts.tests.helpers import (
    capture_auth_events,
    post_json,
    uid,
    verified_user_with_workspace,
)
from apps.accounts.tokens import make_email_verification_token
from apps.workspaces.models import Workspace
from apps.workspaces.models.member import WorkspaceMember, WorkspaceRole

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_signup_queues_verification_without_creating_workspace(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[int] = []
    monkeypatch.setattr(
        auth_flows,
        "send_verification_email",
        SimpleNamespace(enqueue=enqueued.append),
    )

    response = post_json(
        client,
        "/auth/signup/",
        {
            "email": "ada@example.com",
            "password": "test-pass-phrase",
            "full_name": "Ada Lovelace",
        },
    )

    body = response.json()
    user = User.objects.get(email="ada@example.com")
    assert response.status_code == 201
    assert body["email_verification_required"] is True
    assert "workspace" not in body
    assert enqueued == [user.pk]
    assert not user.is_email_verified
    assert "_auth_user_id" not in client.session
    assert not Workspace.objects.filter(owner=user).exists()
    assert not WorkspaceMember.objects.filter(user=user).exists()


def test_verify_email_creates_personal_workspace(client: Client) -> None:
    user = User.objects.create_user(
        email="grace@example.com",
        password="test-pass-phrase",
        full_name="Grace Hopper",
    )
    token = make_email_verification_token(user)

    response = post_json(client, "/auth/verify-email/", {"uid": uid(user), "token": token})

    body = response.json()
    user.refresh_from_db()
    member = WorkspaceMember.objects.select_related("workspace").get(user=user)
    assert response.status_code == 200
    assert body["already_verified"] is False
    assert body["workspace"]["slug"] == member.workspace.slug
    assert user.is_email_verified
    assert member.role == WorkspaceRole.ADMIN
    assert member.workspace.owner_id == user.pk


def test_verify_email_is_idempotent_for_still_valid_token(client: Client) -> None:
    user = User.objects.create_user(email="repeat@example.com", password="test-pass-phrase")
    token = make_email_verification_token(user)

    first = post_json(client, "/auth/verify-email/", {"uid": uid(user), "token": token})
    second = post_json(client, "/auth/verify-email/", {"uid": uid(user), "token": token})

    member = WorkspaceMember.objects.select_related("workspace").get(user=user)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["already_verified"] is True
    assert second.json()["workspace"]["slug"] == member.workspace.slug
    assert WorkspaceMember.objects.filter(user=user).count() == 1


def test_verify_email_rejects_inactive_user(client: Client) -> None:
    user = User.objects.create_user(email="inactive@example.com", password="test-pass-phrase")
    token = make_email_verification_token(user)
    user.deactivate()

    response = post_json(client, "/auth/verify-email/", {"uid": uid(user), "token": token})

    user.refresh_from_db()
    assert response.status_code == 400
    assert not user.is_email_verified
    assert not WorkspaceMember.objects.filter(user=user).exists()


def test_invalid_verification_does_not_create_workspace(client: Client) -> None:
    user = User.objects.create_user(email="invalid@example.com", password="test-pass-phrase")

    response = post_json(client, "/auth/verify-email/", {"uid": uid(user), "token": "bad"})

    user.refresh_from_db()
    assert response.status_code == 400
    assert not user.is_email_verified
    assert not WorkspaceMember.objects.filter(user=user).exists()


def test_resend_verification_queues_for_unverified_user(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    enqueued: list[int] = []
    monkeypatch.setattr(
        auth_flows,
        "send_verification_email",
        SimpleNamespace(enqueue=enqueued.append),
    )
    user = User.objects.create_user(email="resend@example.com", password="test-pass-phrase")

    response = post_json(client, "/auth/resend-verification/", {"email": "resend@example.com"})

    assert response.status_code == 200
    assert enqueued == [user.pk]


def test_resend_verification_does_not_reveal_missing_or_verified_account(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    enqueued: list[int] = []
    monkeypatch.setattr(
        auth_flows,
        "send_verification_email",
        SimpleNamespace(enqueue=enqueued.append),
    )
    verified_user_with_workspace("verified-resend@example.com")

    missing = post_json(client, "/auth/resend-verification/", {"email": "missing@example.com"})
    verified = post_json(
        client,
        "/auth/resend-verification/",
        {"email": "verified-resend@example.com"},
    )

    assert missing.status_code == 200
    assert verified.status_code == 200
    assert enqueued == []


def test_resend_verification_rate_limits_with_hashed_key(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    events = capture_auth_events(monkeypatch)
    config = AuthFlowConfig()
    email = "limit-verify@example.com"
    key = auth_flows.verification_resend_key(
        SimpleNamespace(META={"REMOTE_ADDR": "203.0.113.10"}),
        email,
        config,
    )

    for _ in range(config.verification_resend_limit):
        response = post_json(client, "/auth/resend-verification/", {"email": email})
        assert response.status_code == 200

    response = post_json(client, "/auth/resend-verification/", {"email": email})

    assert email not in key
    assert key.startswith(config.verification_resend_cache_prefix)
    assert response.status_code == 429
    assert events[-1][0] == "verification_email_resend_blocked"
