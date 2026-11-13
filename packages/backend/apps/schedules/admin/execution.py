from __future__ import annotations

from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.schedules.models import ScheduleExecution


@admin.register(ScheduleExecution)
class ScheduleExecutionAdmin(ModelAdmin):
    list_display = ("schedule", "outcome", "scheduled_for", "started_at", "finished_at")
    list_filter = ("outcome",)
    search_fields = ("schedule__name",)
    autocomplete_fields = ("schedule", "run")
    readonly_fields = (
        "schedule",
        "run",
        "outcome",
        "scheduled_for",
        "started_at",
        "finished_at",
        "skip_reason",
        "error_message",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (None, {"fields": ("schedule", "run", "outcome", "scheduled_for")}),
        ("Timing", {"fields": ("started_at", "finished_at")}),
        ("Errors", {"fields": ("skip_reason", "error_message")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
