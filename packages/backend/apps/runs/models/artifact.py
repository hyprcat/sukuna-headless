from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import models

from apps.accounts.permissions import Action
from apps.core.models import TimestampedModel

if TYPE_CHECKING:
    from apps.workspaces.models.member import WorkspaceMember


class ArtifactKind(models.TextChoices):
    DOCUMENT = "document"
    CODE = "code"
    STRUCTURED_DATA = "structured_data"
    IMAGE = "image"


class Artifact(TimestampedModel):
    run = models.ForeignKey(
        "runs.Run",
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=24, choices=ArtifactKind)
    mime_type = models.CharField(max_length=128, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    storage_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Object-storage key or file path.",
    )
    content_text = models.TextField(
        blank=True,
        default="",
        help_text="Inline content for small text/code artifacts.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "runs_artifact"
        ordering = ("created_at",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("run", "kind")),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"

    def can_be_viewed_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.run.workspace_id and member.can(Action.RUNS_READ)
