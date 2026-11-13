from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.runs.models import RunEvent

if TYPE_CHECKING:
    from django.http import HttpRequest


class RunEventInline(TabularInline):
    model = RunEvent
    extra = 0
    readonly_fields = ("sequence_no", "event_type", "callback_event_id", "payload", "created_at")
    fields = ("sequence_no", "event_type", "callback_event_id", "created_at")
    ordering = ("sequence_no",)
    show_change_link = True

    def has_add_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(RunEvent)
class RunEventAdmin(ModelAdmin):
    list_display = ("run", "sequence_no", "event_type", "callback_event_id", "created_at")
    list_filter = ("event_type",)
    search_fields = ("run__run_uid",)
    readonly_fields = (
        "run",
        "sequence_no",
        "event_type",
        "callback_event_id",
        "batch_id",
        "payload",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (None, {"fields": ("run", "sequence_no", "event_type")}),
        ("Callback", {"fields": ("callback_event_id", "batch_id")}),
        ("Payload", {"fields": ("payload",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
