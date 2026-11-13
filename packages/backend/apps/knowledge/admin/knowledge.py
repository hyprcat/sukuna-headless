from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.knowledge.models import Knowledge

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(Knowledge)
class KnowledgeAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "name",
        "workspace",
        "kind",
        "is_active",
        "content_type",
        "last_indexed_at",
        "created_at",
    )
    list_filter = (
        "is_active",
        "kind",
        ("workspace", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("name", "workspace__name", "workspace__slug")
    autocomplete_fields = ("workspace",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "deactivated_at",
        "last_indexed_at",
        "file_size_bytes",
    )

    fieldsets = (
        (None, {"fields": ("workspace", "name", "description", "kind")}),
        ("Upload", {"fields": ("file", "file_name", "file_size_bytes", "content_type")}),
        ("Connected source", {"fields": ("source_endpoint", "source_config")}),
        ("Status", {"fields": ("is_active", "last_indexed_at")}),
        ("Audit", {"fields": ("created_at", "updated_at", "deactivated_at")}),
    )

    actions_detail = ("activate_knowledge", "deactivate_knowledge", "reindex_now")

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @action(description="Activate knowledge base")
    def activate_knowledge(self, request: HttpRequest, object_id: int) -> None:
        Knowledge.objects.get(pk=object_id).activate()

    @action(description="Deactivate knowledge base")
    def deactivate_knowledge(self, request: HttpRequest, object_id: int) -> None:
        Knowledge.objects.get(pk=object_id).deactivate()

    @action(description="Reindex now", icon="refresh")
    def reindex_now(self, request: HttpRequest, object_id: int) -> None:
        kb = Knowledge.objects.get(pk=object_id)
        kb.reindex()
        messages.success(request, f"Reindex triggered for {kb.name}.")
