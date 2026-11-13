from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.utils import timezone
from freezegun import freeze_time

from apps.api_keys.admin.api_key import APIKeyAdmin
from apps.api_keys.factories import APIKeyFactory, create_with_secret
from apps.api_keys.models import APIKey
from apps.core.exceptions import Conflict, InvalidInput
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def test_create_returns_plain_secret_with_correct_shape() -> None:
    workspace = WorkspaceFactory()

    api_key, secret = APIKey.create_for_workspace(
        workspace, name="prod", scopes=("runs:write", "runs:read")
    )

    assert secret.startswith("ms_")
    assert api_key.key_prefix in secret
    assert api_key.key_hash != secret  # never stored plaintext
    assert api_key.history.count() == 1


def test_create_rejects_unknown_scope() -> None:
    workspace = WorkspaceFactory()

    with pytest.raises(InvalidInput, match="Unknown API key scopes"):
        APIKey.create_for_workspace(workspace, name="bad", scopes=("not:a:scope",))


def test_create_accepts_schema_scopes() -> None:
    workspace = WorkspaceFactory()
    scopes = ("workspace:read", "agents:read", "agents:write", "tools:write", "knowledge:write")

    api_key, _secret = APIKey.create_for_workspace(workspace, name="schema", scopes=scopes)

    assert api_key.scopes == list(scopes)


def test_save_rejects_unknown_scope() -> None:
    api_key = APIKeyFactory.build(workspace=WorkspaceFactory(), scopes=["runs:read", "bad:scope"])

    with pytest.raises(ValidationError, match="Unknown API key scopes"):
        api_key.save()


def test_verify_matches_only_correct_secret() -> None:
    api_key, secret = create_with_secret()

    assert api_key.verify(secret)
    assert not api_key.verify(secret + "x")
    assert not api_key.verify("ms_dev_wrong")


def test_verify_returns_false_after_revoke() -> None:
    api_key, secret = create_with_secret()
    starting_history_count = api_key.history.count()

    api_key.revoke(reason="rotation")

    assert not api_key.verify(secret)
    assert not api_key.is_active()
    assert api_key.history.count() == starting_history_count + 1
    assert api_key.history.first().revoked_at is not None


def test_revoke_twice_is_conflict() -> None:
    api_key, _ = create_with_secret()
    api_key.revoke(reason="first")

    with pytest.raises(Conflict):
        api_key.revoke(reason="second")


def test_revoke_rechecks_stale_instances() -> None:
    api_key, _ = create_with_secret()
    first = APIKey.objects.get(pk=api_key.pk)
    stale = APIKey.objects.get(pk=api_key.pk)

    first.revoke(reason="rotation")

    with pytest.raises(Conflict):
        stale.revoke(reason="second")


def test_existing_key_cannot_move_workspaces() -> None:
    api_key, _ = create_with_secret()
    api_key.workspace = WorkspaceFactory()

    with pytest.raises(Conflict, match="security fields are immutable"):
        api_key.save()


def test_existing_key_cannot_change_secret_or_scopes() -> None:
    api_key, _ = create_with_secret(scopes=("runs:read",))
    api_key.scopes = ["runs:write"]

    with pytest.raises(Conflict, match="security fields are immutable"):
        api_key.save()


def test_direct_revoked_at_save_is_rejected() -> None:
    api_key, _ = create_with_secret(scopes=("runs:read",))
    api_key.revoked_at = timezone.now()

    with pytest.raises(Conflict, match=r"Use APIKey\.revoke"):
        api_key.save(update_fields=("revoked_at", "updated_at"))


def test_queryset_update_rejects_sensitive_fields() -> None:
    api_key, _ = create_with_secret(scopes=("runs:read",))

    with pytest.raises(Conflict, match="security-sensitive"):
        APIKey.objects.filter(pk=api_key.pk).update(scopes=["runs:write"])


def test_bulk_create_is_rejected() -> None:
    api_key = APIKeyFactory.build()

    with pytest.raises(Conflict, match="create_for_workspace"):
        APIKey.objects.bulk_create([api_key])


def test_expired_key_is_inactive() -> None:
    workspace = WorkspaceFactory()
    past = timezone.now() - timedelta(seconds=1)
    api_key, secret = APIKey.create_for_workspace(
        workspace, name="expired", scopes=("runs:read",), expires_at=past
    )

    assert not api_key.is_active()
    assert not api_key.verify(secret)


def test_lookup_by_prefix_excludes_revoked() -> None:
    api_key, _ = create_with_secret(scopes=("runs:read",))
    api_key.revoke(reason="test")

    assert not APIKey.objects.lookup_by_prefix(api_key.key_prefix).exists()


def test_lookup_by_prefix_excludes_expired() -> None:
    workspace = WorkspaceFactory()
    past = timezone.now() - timedelta(minutes=1)
    api_key, _ = APIKey.create_for_workspace(
        workspace, name="expired", scopes=("runs:read",), expires_at=past
    )

    assert not APIKey.objects.lookup_by_prefix(api_key.key_prefix).exists()


def test_record_use_writes_only_once_per_minute() -> None:
    api_key, _ = create_with_secret()

    with freeze_time("2026-01-01 12:00:00") as frozen:
        api_key.record_use()
        first = APIKey.objects.get(pk=api_key.pk).last_used_at
        assert first is not None

        frozen.tick(timedelta(seconds=30))
        api_key.record_use()
        unchanged = APIKey.objects.get(pk=api_key.pk).last_used_at
        assert unchanged == first

        frozen.tick(timedelta(seconds=31))
        api_key.record_use()
        bumped = APIKey.objects.get(pk=api_key.pk).last_used_at
        assert bumped is not None
        assert bumped > first


def test_factory_revoked_trait_creates_inactive_row() -> None:
    api_key = APIKeyFactory(revoked=True)

    assert not api_key.is_active()
    assert api_key.revoked_at is not None


def test_active_manager_excludes_far_future_keys_only_when_expired() -> None:
    workspace = WorkspaceFactory()
    future = timezone.now() + timedelta(days=30)
    active, _ = APIKey.create_for_workspace(
        workspace, name="future", scopes=("runs:read",), expires_at=future
    )

    assert APIKey.objects.active().filter(pk=active.pk).exists()


def test_admin_defaults_to_active_keys() -> None:
    active, _ = create_with_secret(scopes=("runs:read",))
    revoked, _ = create_with_secret(scopes=("runs:read",))
    revoked.revoke(reason="test")
    request = RequestFactory().get("/admin/api_keys/apikey/")
    model_admin = APIKeyAdmin(APIKey, admin.site)

    queryset = model_admin.get_queryset(request)

    assert queryset.filter(pk=active.pk).exists()
    assert not queryset.filter(pk=revoked.pk).exists()


def test_admin_makes_security_fields_readonly_on_existing_keys() -> None:
    api_key, _ = create_with_secret(scopes=("runs:read",))
    request = RequestFactory().get("/admin/api_keys/apikey/")
    model_admin = APIKeyAdmin(APIKey, admin.site)

    readonly = model_admin.get_readonly_fields(request, api_key)

    assert "workspace" in readonly
    assert "scopes" in readonly
    assert "key_hash" in readonly
