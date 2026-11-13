from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.runs.models import Rating

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(Rating)
class RatingAdmin(ModelAdmin):
    list_display = ("run", "score", "created_at")
    list_filter = ("score",)
    search_fields = ("run__run_uid",)
    autocomplete_fields = ("run",)
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("run", "score", "comment")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
