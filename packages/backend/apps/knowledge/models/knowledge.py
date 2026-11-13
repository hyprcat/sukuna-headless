from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import Action
from apps.core.events import record_event
from apps.core.exceptions import Conflict, NotFound
from apps.core.models import TimestampedModel
from apps.knowledge.schemas import KnowledgeFormat

if TYPE_CHECKING:
    from apps.workspaces.models.member import WorkspaceMember


class KnowledgeKind(models.TextChoices):
    DOCUMENT = "document"
    DATASET = "dataset"
    CONNECTED_SOURCE = "connected_source"


def _knowledge_upload_to(instance: Knowledge, filename: str) -> str:
    return f"knowledge/{instance.workspace_id}/{filename}"


class Knowledge(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="knowledge_bases",
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=20, choices=KnowledgeKind.choices)

    file = models.FileField(
        upload_to=_knowledge_upload_to,
        blank=True,
        default="",
        help_text="Uploaded content for document or dataset kinds.",
    )
    file_name = models.CharField(max_length=255, blank=True, default="")
    file_size_bytes = models.PositiveBigIntegerField(blank=True, null=True)
    content_type = models.CharField(max_length=128, blank=True, default="")

    source_endpoint = models.CharField(
        max_length=2048,
        blank=True,
        default="",
        help_text="Connection URL for connected-source kind.",
    )
    source_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Connection parameters for connected-source kind.",
    )

    last_indexed_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    deactivated_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        db_table = "knowledge_knowledge"
        ordering = ("name",)
        verbose_name_plural = "knowledge bases"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("workspace", "name"),
                name="knowledge_workspace_name_uniq",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "is_active")),
            models.Index(fields=("workspace", "kind")),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        fmt = KnowledgeFormat()
        self._validate_description(fmt)
        self._validate_kind_fields()
        self._validate_file(fmt)
        self._validate_source_config(fmt)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def activate(self) -> None:
        if self.is_active:
            return
        self.is_active = True
        self.deactivated_at = None
        self.save(update_fields=("is_active", "deactivated_at", "updated_at"))
        self._emit_event("knowledge_activated")

    def deactivate(self) -> None:
        if not self.is_active:
            return
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.save(update_fields=("is_active", "deactivated_at", "updated_at"))
        self._emit_event("knowledge_deactivated")

    def reindex(self) -> None:
        self.last_indexed_at = timezone.now()
        self.save(update_fields=("last_indexed_at", "updated_at"))
        self._emit_event("knowledge_reindex_requested")

    def rename(self, new_name: str) -> None:
        if not new_name.strip():
            raise Conflict("Knowledge base name must not be blank.")
        dupe = (
            type(self)
            .objects.filter(workspace_id=self.workspace_id, name=new_name)
            .exclude(pk=self.pk)
            .exists()
        )
        if dupe:
            raise Conflict("A knowledge base with this name already exists in the workspace.")
        self.name = new_name
        self.save(update_fields=("name", "updated_at"))

    @classmethod
    def for_workspace(
        cls,
        workspace_id: int,
        *,
        kind: str | None = None,
        is_active: bool | None = None,
    ) -> models.QuerySet[Knowledge]:
        qs = cls.objects.filter(workspace_id=workspace_id)
        if kind is not None:
            qs = qs.filter(kind=kind)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    @classmethod
    def get_for_workspace(cls, workspace_id: int, pk: object) -> Knowledge | None:
        return cls.objects.filter(workspace_id=workspace_id, pk=pk).first()

    @classmethod
    def get_for_workspace_or_raise(cls, workspace_id: int, pk: object) -> Knowledge:
        try:
            return cls.objects.get(pk=pk, workspace_id=workspace_id)
        except cls.DoesNotExist as exc:
            raise NotFound("Knowledge base not found.") from exc

    @classmethod
    def create_for_workspace(
        cls,
        workspace_id: int,
        *,
        name: str,
        kind: str,
        description: str = "",
        source_endpoint: str = "",
        source_config: dict[str, Any] | None = None,
    ) -> Knowledge:
        return cls.objects.create(
            workspace_id=workspace_id,
            name=name,
            kind=kind,
            description=description,
            source_endpoint=source_endpoint,
            source_config=source_config or {},
        )

    def update(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        source_endpoint: str | None = None,
        source_config: dict[str, Any] | None = None,
    ) -> None:
        with transaction.atomic():
            if name is not None:
                self.rename(name)
            changed: list[str] = []
            if description is not None:
                self.description = description
                changed.append("description")
            if source_endpoint is not None:
                self.source_endpoint = source_endpoint
                changed.append("source_endpoint")
            if source_config is not None:
                self.source_config = source_config
                changed.append("source_config")
            if changed:
                self.save(update_fields=[*changed, "updated_at"])

    def can_be_edited_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.KNOWLEDGE_WRITE)

    def _emit_event(self, name: str) -> None:
        record_event(
            name,
            distinct_id=str(self.workspace_id),
            properties={
                "knowledge_id": str(self.pk),
                "knowledge_name": self.name,
                "kind": self.kind,
            },
        )

    def _validate_description(self, fmt: KnowledgeFormat) -> None:
        if len(self.description) > fmt.max_description_length:
            raise ValidationError(
                {"description": f"Exceeds {fmt.max_description_length} characters."}
            )

    def _validate_kind_fields(self) -> None:
        upload_kinds = {KnowledgeKind.DOCUMENT, KnowledgeKind.DATASET}
        if self.kind in upload_kinds and not self.file:
            raise ValidationError({"file": f"A file is required for {self.kind} kind."})
        if self.kind == KnowledgeKind.CONNECTED_SOURCE and not self.source_endpoint.strip():
            raise ValidationError({"source_endpoint": "Required for connected-source kind."})

    def _validate_file(self, fmt: KnowledgeFormat) -> None:
        if not self.file:
            return
        if self.file_size_bytes and self.file_size_bytes > fmt.max_file_size_bytes:
            raise ValidationError({"file": f"File exceeds {fmt.max_file_size_bytes} bytes."})
        if not self.content_type:
            raise ValidationError({"content_type": "Content type is required for uploaded files."})
        if self.content_type not in fmt.allowed_content_types:
            raise ValidationError({"file": f"Content type {self.content_type!r} is not allowed."})

    def _validate_source_config(self, fmt: KnowledgeFormat) -> None:
        if not self.source_config:
            return
        if not isinstance(self.source_config, dict):
            raise ValidationError({"source_config": "Must be a JSON object."})
        raw = json.dumps(self.source_config)
        if len(raw.encode()) > fmt.max_source_config_bytes:
            raise ValidationError(
                {"source_config": f"Exceeds {fmt.max_source_config_bytes} bytes."}
            )
