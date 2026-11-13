from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import Conflict

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from apps.api_keys.models.api_key import APIKey


class APIKeyQuerySet(models.QuerySet["APIKey"]):
    def active(self) -> APIKeyQuerySet:
        now = timezone.now()
        return self.filter(revoked_at__isnull=True).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )

    def for_workspace(self, workspace_pk: int) -> APIKeyQuerySet:
        return self.filter(workspace_id=workspace_pk)

    def lookup_by_prefix(self, prefix: str) -> APIKeyQuerySet:
        return self.active().filter(key_prefix=prefix)

    def update(self, **kwargs: Any) -> int:
        if _guarded_fields() & set(kwargs):
            raise Conflict("Use APIKey model methods to change security-sensitive fields.")
        return super().update(**kwargs)

    def bulk_create(
        self,
        objs: Iterable[APIKey],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[APIKey]:
        raise Conflict("Use APIKey.create_for_workspace() to mint API keys.")


class APIKeyManager(models.Manager["APIKey"]):
    def get_queryset(self) -> APIKeyQuerySet:
        return APIKeyQuerySet(self.model, using=self._db)

    def active(self) -> APIKeyQuerySet:
        return self.get_queryset().active()

    def for_workspace(self, workspace_pk: int) -> APIKeyQuerySet:
        return self.get_queryset().for_workspace(workspace_pk)

    def lookup_by_prefix(self, prefix: str) -> APIKeyQuerySet:
        return self.get_queryset().lookup_by_prefix(prefix)

    def bulk_create(
        self,
        objs: Iterable[APIKey],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[APIKey]:
        raise Conflict("Use APIKey.create_for_workspace() to mint API keys.")


def _guarded_fields() -> set[str]:
    fields = {"workspace", "workspace_id", "key_prefix", "key_hash", "scopes"}
    return fields | {"created_by", "created_by_id", "revoked_at"}
