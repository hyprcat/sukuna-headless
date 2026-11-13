from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from apps.runs.models import Conversation

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(Conversation)
class ConversationAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "conversation_uid",
        "workspace",
        "agent",
        "end_user",
        "title",
        "created_at",
    )
    list_filter = (
        ("workspace", admin.RelatedOnlyFieldListFilter),
        ("agent", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "conversation_uid",
        "title",
        "workspace__name",
        "workspace__slug",
    )
    autocomplete_fields = ("workspace", "agent", "end_user")
    readonly_fields = (
        "conversation_uid",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            None,
            {"fields": ("conversation_uid", "workspace", "agent", "end_user", "title")},
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
