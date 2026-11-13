from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.api_keys.hashing import hash_secret, verify_secret
from apps.api_keys.models.querysets import APIKeyManager, APIKeyQuerySet
from apps.api_keys.schemas.config import APIKeyFormat
from apps.api_keys.scopes import APIKeyScopes
from apps.core.events import record_event
from apps.core.exceptions import Conflict, InvalidInput, NotFound
from apps.core.models import TimestampedModel
from config.runtime import runtime

if TYPE_CHECKING:
    from collections.abc import Iterable

    from apps.accounts.models import User
    from apps.workspaces.models import Workspace


def _generate_secret(fmt: APIKeyFormat) -> tuple[str, str]:
    """Return ``(full_secret, prefix)`` — ``ms_<env>_<base62-random>`` + 8-char prefix."""
    random_part = "".join(secrets.choice(fmt.base62_alphabet) for _ in range(fmt.random_length))
    secret = f"{fmt.namespace}_{runtime.environment}_{random_part}"
    return secret, random_part[: fmt.prefix_length]


def _validate_scopes(scopes: Iterable[str]) -> list[str]:
    """Reject any scope string outside the closed `APIKeyScopes` vocabulary."""
    scope_list = list(scopes)
    invalid = set(scope_list) - APIKeyScopes().values
    if invalid:
        raise ValueError(f"Unknown API key scopes: {sorted(invalid)}")
    return scope_list


def _validate_create_scopes(scopes: Iterable[str]) -> list[str]:
    try:
        return _validate_scopes(scopes)
    except ValueError as exc:
        raise InvalidInput(str(exc), field="scopes") from exc


class APIKey(TimestampedModel):
    """Workspace-scoped credential for SDK / direct-RPC auth.

    The plain secret is exposed exactly once — at creation, via
    :meth:`create_for_workspace`. Thereafter only the prefix is visible; the
    full key is unrecoverable. Rotation = revoke + re-create.
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    name = models.CharField(max_length=120)
    key_prefix = models.CharField(max_length=16, db_index=True)
    key_hash = models.CharField(max_length=255)
    scopes = ArrayField(base_field=models.CharField(max_length=64), default=list)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="api_keys_created",
    )
    last_used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()

    objects: ClassVar[APIKeyManager] = APIKeyManager()
    _allow_revoke_save: bool = False

    class Meta:
        db_table = "api_keys_apikey"
        ordering = ("-created_at",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "revoked_at")),
            models.Index(fields=("key_prefix",)),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="apikey_name_non_empty",
            ),
            models.CheckConstraint(
                condition=models.Q(key_prefix__regex=r"^[0-9A-Za-z]{8}$"),
                name="apikey_prefix_base62_8",
            ),
            models.CheckConstraint(
                condition=~models.Q(key_hash=""),
                name="apikey_hash_non_empty",
            ),
            models.CheckConstraint(
                condition=models.Q(scopes__contained_by=tuple(sorted(APIKeyScopes().values))),
                name="apikey_scopes_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.masked_value()})"

    def masked_value(self) -> str:
        fmt = APIKeyFormat()
        return f"{fmt.namespace}_{runtime.environment}_{self.key_prefix}..."

    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    def verify(self, presented: str) -> bool:
        """Constant-time match of `presented` against the stored hash."""
        if not self.is_active():
            return False
        return verify_secret(presented, self.key_hash)

    def clean(self) -> None:
        super().clean()
        try:
            self.scopes = _validate_scopes(self.scopes)
        except ValueError as exc:
            raise ValidationError({"scopes": str(exc)}) from exc

    def save(
        self,
        *,
        force_insert: bool | tuple[models.base.ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        self.full_clean()
        with transaction.atomic():
            previous = self._locked_previous_values()
            self._guard_security_fields(previous)
            super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=using,
                update_fields=update_fields,
            )

    def record_use(self) -> None:
        """Update `last_used_at` once per minute per row at most.

        Avoids a hot write on every request for keys that fire continuously,
        while still surfacing recency to operators within a minute.
        """
        throttle = timedelta(seconds=APIKeyFormat().record_use_throttle_seconds)
        threshold = timezone.now() - throttle
        type(self).objects.filter(pk=self.pk).filter(
            Q(last_used_at__isnull=True) | Q(last_used_at__lt=threshold)
        ).update(last_used_at=timezone.now())

    @transaction.atomic
    def revoke(self, *, reason: str) -> None:
        key = type(self).objects.select_for_update().get(pk=self.pk)
        if key.revoked_at is not None:
            raise Conflict("API key already revoked.")
        key.revoked_at = timezone.now()
        key._allow_revoke_save = True
        key.save(update_fields=("revoked_at", "updated_at"))
        self.revoked_at = key.revoked_at
        record_event(
            "api_key_revoked",
            distinct_id=str(key.workspace_id),
            properties={"api_key_id": key.pk, "key_prefix": key.key_prefix, "reason": reason},
        )

    def _locked_previous_values(
        self,
    ) -> tuple[int, int | None, str, str, list[str], datetime | None] | None:
        if self.pk is None:
            return None
        fields = ("workspace_id", "created_by_id", "key_prefix", "key_hash", "scopes", "revoked_at")
        return (
            type(self).objects.select_for_update().filter(pk=self.pk).values_list(*fields).first()
        )

    def _guard_security_fields(
        self,
        previous: tuple[int, int | None, str, str, list[str], datetime | None] | None,
    ) -> None:
        if previous is None:
            return
        workspace_id, created_by_id, key_prefix, key_hash, scopes, revoked_at = previous
        previous_security = (workspace_id, created_by_id, key_prefix, key_hash, scopes)
        current_security = (
            self.workspace_id,
            self.created_by_id,
            self.key_prefix,
            self.key_hash,
            self.scopes,
        )
        if previous_security != current_security:
            raise Conflict("API key security fields are immutable; revoke and create a new key.")
        if revoked_at != self.revoked_at and not getattr(self, "_allow_revoke_save", False):
            raise Conflict("Use APIKey.revoke() to revoke keys.")

    @classmethod
    def list_for_workspace(cls, workspace_pk: int, *, show_revoked: bool = False) -> APIKeyQuerySet:
        base = cls.objects if show_revoked else cls.objects.active()
        return base.for_workspace(workspace_pk).select_related("created_by")

    @classmethod
    def get_for_workspace(cls, workspace_pk: int, pk: int | str) -> APIKey | None:
        return (
            cls.objects.for_workspace(workspace_pk)
            .select_related("created_by")
            .filter(pk=pk)
            .first()
        )

    @classmethod
    def get_for_workspace_or_raise(cls, workspace_pk: int, pk: int | str) -> APIKey:
        try:
            return cls.objects.for_workspace(workspace_pk).get(pk=pk)
        except cls.DoesNotExist as exc:
            raise NotFound("API key not found.") from exc

    @classmethod
    @transaction.atomic
    def create_for_workspace(
        cls,
        workspace: Workspace,
        *,
        name: str,
        scopes: Iterable[str],
        created_by: User | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[APIKey, str]:
        secret, prefix = _generate_secret(APIKeyFormat())
        api_key = cls._create_row(
            workspace=workspace,
            name=name,
            key_prefix=prefix,
            secret=secret,
            scopes=_validate_create_scopes(scopes),
            created_by=created_by,
            expires_at=expires_at,
        )
        record_event(
            "api_key_created",
            distinct_id=str(api_key.workspace_id),
            properties={
                "api_key_id": api_key.pk,
                "key_prefix": api_key.key_prefix,
                "scopes": api_key.scopes,
            },
        )
        return api_key, secret

    @classmethod
    def _create_row(
        cls,
        *,
        workspace: Workspace,
        name: str,
        key_prefix: str,
        secret: str,
        scopes: list[str],
        created_by: User | None,
        expires_at: datetime | None,
    ) -> APIKey:
        return cls.objects.create(
            workspace=workspace,
            name=name,
            key_prefix=key_prefix,
            key_hash=hash_secret(secret),
            scopes=scopes,
            created_by=created_by,
            expires_at=expires_at,
        )
