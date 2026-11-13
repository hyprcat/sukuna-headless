from __future__ import annotations

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from apps.policies.models import Policy


@admin.register(Policy)
class PolicyAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("name", "workspace", "created_at", "updated_at")
    list_filter = (("workspace", admin.RelatedOnlyFieldListFilter),)
    search_fields = ("name", "workspace__name", "workspace__slug")
    autocomplete_fields = ("workspace",)
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("workspace", "name")}),
        ("Action restrictions", {"fields": ("action_restrictions",)}),
        ("Domain restrictions", {"fields": ("domain_restrictions",)}),
        ("Output restrictions", {"fields": ("output_restrictions",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
