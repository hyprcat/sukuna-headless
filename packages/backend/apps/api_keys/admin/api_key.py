from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.api_keys.models import APIKey
from apps.core.exceptions import Conflict

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


@admin.register(APIKey)
class APIKeyAdmin(SimpleHistoryAdmin, ModelAdmin):
    """Read-mostly view — secrets are unknowable post-creation, only the prefix shows."""

    list_display = (
        "name",
        "key_prefix",
        "workspace",
        "scopes",
        "last_used_at",
        "revoked_at",
        "created_at",
    )
    list_filter = ("revoked_at", "expires_at", "workspace")
    search_fields = ("name", "key_prefix", "workspace__slug", "workspace__name")
    autocomplete_fields = ("workspace", "created_by")
    readonly_fields = (
        "key_prefix",
        "key_hash",
        "last_used_at",
        "revoked_at",
        "created_at",
        "updated_at",
    )
    actions_list = ("revoke_keys",)
    actions = ("revoke_keys",)

    fieldsets = (
        (None, {"fields": ("workspace", "name", "scopes", "expires_at")}),
        ("Secret", {"fields": ("key_prefix", "key_hash")}),
        ("Status", {"fields": ("last_used_at", "revoked_at")}),
        ("Audit", {"fields": ("created_by", "created_at", "updated_at")}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[APIKey]:
        return super().get_queryset(request).filter(revoked_at__isnull=True)  # type: ignore[no-any-return]

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: APIKey | None = None,
    ) -> tuple[str, ...]:
        fields = tuple(super().get_readonly_fields(request, obj))
        if obj is None:
            return fields
        immutable = ("workspace", "created_by", "key_prefix", "key_hash", "scopes")
        return tuple(dict.fromkeys((*fields, *immutable)))

    @action(description="Revoke key", icon="block")
    def revoke_keys(self, request: HttpRequest, queryset: QuerySet[APIKey]) -> None:
        revoked = 0
        for key in queryset.filter(revoked_at__isnull=True).iterator(chunk_size=200):
            try:
                key.revoke(reason="Revoked via admin")
            except Conflict:
                continue
            revoked += 1
        self.message_user(request, f"Revoked {revoked} API key(s).", messages.SUCCESS)
