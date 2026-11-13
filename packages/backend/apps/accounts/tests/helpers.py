from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.models import User
from apps.accounts.services import auth_flows
from apps.accounts.views import auth as auth_views
from apps.workspaces.models import Workspace

if TYPE_CHECKING:
    import pytest
    from django.test import Client


def post_json(client: Client, path: str, payload: dict[str, Any]):
    return client.post(path, data=json.dumps(payload), content_type="application/json")


def uid(user: User) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))


def verified_user_with_workspace(email: str) -> tuple[User, Workspace]:
    user = User.objects.create_user(email=email, password="test-pass-phrase")
    user.verify_email()
    workspace = Workspace.objects.create(name="Midsphere", slug="midsphere", owner=user)
    return user, workspace


def capture_auth_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        auth_views,
        "record_event",
        lambda name, **kwargs: events.append((name, kwargs)),
    )
    monkeypatch.setattr(
        auth_flows,
        "record_event",
        lambda name, **kwargs: events.append((name, kwargs)),
    )
    return events
