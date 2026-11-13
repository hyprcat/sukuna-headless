"""Factories for `APIKey` rows.

The plain secret is only knowable at creation time, so factories return
``(api_key, plain_secret)`` via the ``create_with_secret`` helper instead of
the usual single-object ``factory_boy`` shape. ``APIKeyFactory.create()``
still works when a test only needs a row (the plain secret is dropped).
"""

from __future__ import annotations

from typing import Any

import factory
from django.utils import timezone

from apps.api_keys.models import APIKey
from apps.api_keys.scopes import APIKeyScopes
from apps.workspaces.factories import WorkspaceFactory


def create_with_secret(
    *,
    workspace: Any = None,
    name: str = "Test key",
    scopes: tuple[str, ...] = ("runs:write", "runs:read"),
    revoked: bool = False,
) -> tuple[APIKey, str]:
    """Mint an APIKey + return the plain secret. Tests use this to verify auth."""
    workspace = workspace or WorkspaceFactory()
    valid = APIKeyScopes().values
    for scope in scopes:
        assert scope in valid, f"unknown test scope: {scope}"
    api_key, secret = APIKey.create_for_workspace(workspace, name=name, scopes=scopes)
    if revoked:
        api_key.revoke(reason="factory")
    return api_key, secret


class APIKeyFactory(factory.django.DjangoModelFactory):
    """Direct row factory — bypasses `create_for_workspace`, hash is unverifiable.

    Use `create_with_secret` when the test needs to call `verify(...)`. This
    factory exists for tests that only need the row's metadata.
    """

    class Meta:
        model = APIKey

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Key {n}")
    key_prefix = factory.Sequence(lambda n: f"{n:08d}")
    key_hash = "scrypt$invalid$placeholder"
    scopes = factory.LazyFunction(lambda: ["runs:write", "runs:read"])

    class Params:
        revoked = factory.Trait(revoked_at=factory.LazyFunction(timezone.now))
