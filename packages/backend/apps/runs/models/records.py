"""Append-only run records: events and manifest metadata."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, ClassVar

from cryptography.fernet import Fernet
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.exceptions import Conflict
from apps.core.models import TimestampedModel


class RunEventQuerySet(models.QuerySet["RunEvent"]):
    def for_run(self, run_id: int) -> RunEventQuerySet:
        return self.filter(run_id=run_id).order_by("sequence_no")

    def update(self, **kwargs: Any) -> int:
        raise Conflict("RunEvent is append-only.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise Conflict("RunEvent is append-only.")


class RunEvent(TimestampedModel):
    run = models.ForeignKey(
        "runs.Run",
        on_delete=models.CASCADE,
        related_name="events",
    )
    sequence_no = models.PositiveIntegerField()
    event_type = models.CharField(max_length=32, db_index=True)
    payload = models.JSONField()
    callback_event_id = models.UUIDField(null=True, blank=True, unique=True)
    batch_id = models.UUIDField(null=True, blank=True)
    objects = RunEventQuerySet.as_manager()

    class Meta:
        db_table = "runs_runevent"
        ordering = ("sequence_no",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("run", "sequence_no"),
                name="runs_runevent_run_seq_uniq",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("run", "sequence_no")),
        ]

    def __str__(self) -> str:
        return f"Event #{self.sequence_no} ({self.event_type}) on run {self.run_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise Conflict("RunEvent is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise Conflict("RunEvent is append-only.")


class RunManifestRecord(TimestampedModel):
    manifest_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    run = models.ForeignKey(
        "runs.Run",
        on_delete=models.CASCADE,
        related_name="manifest_records",
    )
    sandbox_id = models.CharField(max_length=128)
    signing_key_id = models.CharField(max_length=128)
    manifest_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 hex digest of the signed manifest body.",
    )
    callback_auth_encrypted = models.BinaryField(
        help_text="Fernet-encrypted per-run HMAC key for callback verification.",
    )
    schema_version = models.PositiveSmallIntegerField(default=1)
    expires_at = models.DateTimeField()

    history = HistoricalRecords()

    class Meta:
        db_table = "runs_manifest_record"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Manifest {self.manifest_id}"

    def decrypt_callback_auth(self) -> bytes:
        from config.runtime import runtime  # noqa: PLC0415

        f = Fernet(runtime.fernet_encryption_key.encode())
        return f.decrypt(bytes(self.callback_auth_encrypted))

    @staticmethod
    def encrypt_callback_auth(raw_key: bytes) -> bytes:
        from config.runtime import runtime  # noqa: PLC0415

        f = Fernet(runtime.fernet_encryption_key.encode())
        return f.encrypt(raw_key)

    @staticmethod
    def compute_manifest_hash(manifest_body: bytes) -> str:
        return hashlib.sha256(manifest_body).hexdigest()
