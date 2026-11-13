from __future__ import annotations

from typing import ClassVar

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from apps.billing.models import BillingRate


@admin.register(BillingRate)
class BillingRateAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "model_tier",
        "token_input_rate",
        "token_output_rate",
        "tool_call_rate",
        "is_active",
        "created_at",
    )
    list_filter = ("model_tier", "is_active")
    search_fields = ("model_tier",)
    readonly_fields: ClassVar[tuple[str, ...]] = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("model_tier", "is_active")}),
        ("Rates", {"fields": ("token_input_rate", "token_output_rate", "tool_call_rate")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
