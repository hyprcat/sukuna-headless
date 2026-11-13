from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from apps.billing.models import LedgerEntry

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(LedgerEntry)
class LedgerEntryAdmin(SimpleHistoryAdmin, ModelAdmin):
    """Append-only ledger — fully read-only in the admin.

    Corrections go through the wallet's manual-adjustment action so the
    note/reference invariants are enforced; nothing here can mutate state.
    """

    list_display = ("wallet", "kind", "delta_usd", "currency", "reference", "created_at")
    list_filter = ("kind", "wallet__workspace")
    search_fields = ("reference", "note", "wallet__workspace__slug")
    autocomplete_fields = ("wallet",)
    readonly_fields: ClassVar[tuple[str, ...]] = (
        "wallet",
        "kind",
        "delta_usd",
        "currency",
        "reference",
        "note",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("wallet", "kind", "delta_usd", "currency", "reference", "note")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
