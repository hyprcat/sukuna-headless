from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.runs.models import Artifact

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(Artifact)
class ArtifactAdmin(ModelAdmin):
    list_display = ("name", "kind", "run", "size_bytes", "created_at")
    list_filter = ("kind",)
    search_fields = ("name", "run__run_uid")
    autocomplete_fields = ("run",)
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("run", "name", "kind", "mime_type")}),
        ("Storage", {"fields": ("storage_path", "size_bytes", "content_text")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
