from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from apps.billing.models import WebhookDelivery

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(SimpleHistoryAdmin, ModelAdmin):
    """Inserted at every webhook edge; fully read-only here for forensics."""

    list_display = ("provider", "event_id", "received_at", "processed_at")
    list_filter = ("provider", "processed_at")
    search_fields = ("event_id", "payload_hash")
    readonly_fields: ClassVar[tuple[str, ...]] = (
        "provider",
        "event_id",
        "received_at",
        "processed_at",
        "payload_hash",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("provider", "event_id")}),
        ("Status", {"fields": ("received_at", "processed_at", "payload_hash")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
