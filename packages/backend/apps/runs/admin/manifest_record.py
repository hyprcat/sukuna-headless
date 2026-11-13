from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from apps.runs.models import RunManifestRecord

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(RunManifestRecord)
class RunManifestRecordAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "manifest_id",
        "run",
        "sandbox_id",
        "schema_version",
        "expires_at",
        "created_at",
    )
    list_filter = (
        "schema_version",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "manifest_id",
        "sandbox_id",
        "signing_key_id",
        "run__run_uid",
    )
    readonly_fields = (
        "manifest_id",
        "run",
        "sandbox_id",
        "signing_key_id",
        "manifest_hash",
        "schema_version",
        "expires_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("manifest_id", "run", "sandbox_id")}),
        ("Signing", {"fields": ("signing_key_id", "manifest_hash", "schema_version")}),
        ("Expiry", {"fields": ("expires_at",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
    exclude = ("callback_auth_encrypted",)

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
