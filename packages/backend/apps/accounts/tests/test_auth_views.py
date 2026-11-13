from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import User
from apps.accounts.schemas.config import AuthFlowConfig
from apps.accounts.services import auth_flows
from apps.accounts.tests.helpers import (
    capture_auth_events,
    post_json,
    uid,
    verified_user_with_workspace,
)
from apps.workspaces.models import Workspace, WorkspaceMember

pytestmark = pytest.mark.django_db


def test_login_creates_dashboard_session(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    events = capture_auth_events(monkeypatch)
    user, workspace = verified_user_with_workspace("login@example.com")
    starting_history_count = user.history.count()

    response = post_json(
        client,
        "/auth/login/",
        {"email": "login@example.com", "password": "test-pass-phrase"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["workspace_slug"] == workspace.slug
    assert body["user"]["email_verified"] is True
    assert body["workspaces"] == [
        {"slug": workspace.slug, "name": workspace.name, "role": "admin"},
    ]
    assert client.session["_auth_user_id"] == str(user.pk)
    assert events[-1][0] == "user_logged_in"
    assert user.history.count() == starting_history_count + 1


def test_login_rejects_invalid_credentials(client: Client) -> None:
    verified_user_with_workspace("bad-login@example.com")

    response = post_json(
        client,
        "/auth/login/",
        {"email": "bad-login@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert "_auth_user_id" not in client.session


def test_login_rejects_unverified_user(client: Client) -> None:
    User.objects.create_user(email="pending@example.com", password="test-pass-phrase")

    response = post_json(
        client,
        "/auth/login/",
        {"email": "pending@example.com", "password": "test-pass-phrase"},
    )

    body = response.json()
    assert response.status_code == 403
    assert body["email_verification_required"] is True
    assert "_auth_user_id" not in client.session


def test_login_rate_limits_repeated_invalid_credentials(client: Client) -> None:
    cache.clear()
    config = AuthFlowConfig()
    verified_user_with_workspace("rate-limit@example.com")

    for _ in range(config.login_attempt_limit):
        response = post_json(
            client,
            "/auth/login/",
            {"email": "rate-limit@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401

    response = post_json(
        client,
        "/auth/login/",
        {"email": "rate-limit@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 429
    assert "_auth_user_id" not in client.session


def test_logout_clears_dashboard_session(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    events = capture_auth_events(monkeypatch)
    user, _workspace = verified_user_with_workspace("logout@example.com")
    client.force_login(user)

    response = post_json(client, "/auth/logout/", {})

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert events[-1][0] == "user_logged_out"


def test_forgot_password_queues_reset_for_active_user(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = capture_auth_events(monkeypatch)
    enqueued: list[int] = []
    monkeypatch.setattr(
        auth_flows,
        "send_password_reset_email",
        SimpleNamespace(enqueue=enqueued.append),
    )
    user = User.objects.create_user(email="reset@example.com", password="test-pass-phrase")

    response = post_json(client, "/auth/forgot-password/", {"email": "reset@example.com"})

    assert response.status_code == 200
    assert enqueued == [user.pk]
    assert events[-1][0] == "password_reset_requested"


def test_forgot_password_does_not_reveal_missing_account(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[int] = []
    monkeypatch.setattr(
        auth_flows,
        "send_password_reset_email",
        SimpleNamespace(enqueue=enqueued.append),
    )

    response = post_json(client, "/auth/forgot-password/", {"email": "missing@example.com"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert enqueued == []


def test_forgot_password_rate_limits_reset_requests(client: Client) -> None:
    cache.clear()
    config = AuthFlowConfig()

    for _ in range(config.password_reset_request_limit):
        response = post_json(client, "/auth/forgot-password/", {"email": "limit@example.com"})
        assert response.status_code == 200

    response = post_json(client, "/auth/forgot-password/", {"email": "limit@example.com"})

    assert response.status_code == 429


def test_password_reset_changes_password_and_rejects_token_reuse(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = capture_auth_events(monkeypatch)
    user = User.objects.create_user(email="new-pass@example.com", password="test-pass-phrase")
    token = default_token_generator.make_token(user)
    starting_history_count = user.history.count()

    response = post_json(
        client,
        "/auth/reset-password/",
        {"uid": uid(user), "token": token, "password": "better-pass-8264"},
    )
    user.refresh_from_db()

    assert response.status_code == 200
    assert user.check_password("better-pass-8264")
    assert events[-1][0] == "password_reset_completed"
    assert user.history.count() == starting_history_count + 1
    assert "password" not in {field.name for field in user.history.model._meta.fields}

    response = post_json(
        client,
        "/auth/reset-password/",
        {"uid": uid(user), "token": token, "password": "another-pass-8264"},
    )
    user.refresh_from_db()

    assert response.status_code == 400
    assert user.check_password("better-pass-8264")


def test_password_reset_rechecks_token_inside_completion(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User.objects.create_user(email="stale-token@example.com", password="test-pass-phrase")
    monkeypatch.setattr(
        "apps.accounts.views.auth._reset_password_validation_error",
        lambda _user, _token, _pw: None,
    )

    response = post_json(
        client,
        "/auth/reset-password/",
        {"uid": uid(user), "token": "stale-token", "password": "better-pass-8264"},
    )
    user.refresh_from_db()

    assert response.status_code == 400
    assert user.check_password("test-pass-phrase")


def test_password_reset_invalidates_existing_sessions(client: Client) -> None:
    other_client = Client()
    user = User.objects.create_user(email="sessions@example.com", password="test-pass-phrase")
    client.force_login(user)
    other_client.force_login(user)
    user.refresh_from_db()
    token = default_token_generator.make_token(user)

    response = post_json(
        client,
        "/auth/reset-password/",
        {"uid": uid(user), "token": token, "password": "better-pass-8264"},
    )

    assert response.status_code == 200
    assert client.get("/auth/me/").status_code == 401
    assert other_client.get("/auth/me/").status_code == 401


def test_me_returns_user_and_workspaces(client: Client) -> None:
    user, workspace = verified_user_with_workspace("me@example.com")
    client.force_login(user)

    response = client.get("/auth/me/")

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["user"]["email"] == "me@example.com"
    assert body["user"]["full_name"] == user.full_name
    assert body["user"]["email_verified"] is True
    assert body["workspace_slug"] == workspace.slug
    assert body["workspaces"] == [
        {"slug": workspace.slug, "name": workspace.name, "role": "admin"},
    ]


def test_me_repairs_legacy_owner_workspace_membership(client: Client) -> None:
    user = User.objects.create_user(email="legacy-owner@example.com", password="test-pass-phrase")
    user.verify_email()
    Workspace.objects.bulk_create([Workspace(name="Legacy", slug="legacy", owner=user)])
    client.force_login(user)

    response = client.get("/auth/me/")

    body = response.json()
    assert response.status_code == 200
    assert body["workspace_slug"] == "legacy"
    assert body["workspaces"] == [{"slug": "legacy", "name": "Legacy", "role": "admin"}]
    assert WorkspaceMember.objects.filter(user=user, workspace__slug="legacy").exists()


def test_me_returns_multiple_workspaces(client: Client) -> None:
    user, workspace1 = verified_user_with_workspace("multi@example.com")
    workspace2 = Workspace.objects.create(name="Second", slug="second", owner=user)
    client.force_login(user)

    response = client.get("/auth/me/")

    body = response.json()
    assert response.status_code == 200
    assert len(body["workspaces"]) == 2
    slugs = [w["slug"] for w in body["workspaces"]]
    assert workspace1.slug in slugs
    assert workspace2.slug in slugs
    assert body["workspace_slug"] == body["workspaces"][0]["slug"]
