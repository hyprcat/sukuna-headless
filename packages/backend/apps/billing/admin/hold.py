from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.billing.models import BillingHold
from apps.core.exceptions import DomainError

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


@admin.register(BillingHold)
class BillingHoldAdmin(SimpleHistoryAdmin, ModelAdmin):
    """Read-mostly. Holds are created by the run orchestration service."""

    list_display = (
        "run",
        "wallet",
        "amount_reserved_usd",
        "amount_consumed_usd",
        "status",
        "expires_at",
        "settled_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "run__run_uid",
        "wallet__workspace__slug",
        "wallet__workspace__name",
    )
    autocomplete_fields = ("run", "wallet")
    readonly_fields: ClassVar[tuple[str, ...]] = (
        "run",
        "wallet",
        "amount_reserved_usd",
        "amount_consumed_usd",
        "status",
        "settled_at",
        "expires_at",
        "metadata",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("run", "wallet", "status")}),
        ("Amounts", {"fields": ("amount_reserved_usd", "amount_consumed_usd")}),
        ("Timing", {"fields": ("expires_at", "settled_at")}),
        ("Extra", {"fields": ("metadata",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
    actions_detail = ("release_hold_action", "force_settle_action")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @action(description="Release hold", icon="lock_open", permissions=["change"])
    def release_hold_action(self, request: HttpRequest, object_id: int) -> HttpResponse:
        hold = self._get_hold(request, object_id)
        try:
            hold.release()
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Hold released — reserved balance freed.")
        return redirect(reverse("admin:billing_billinghold_change", args=[object_id]))

    @action(description="Force settle", icon="gavel", permissions=["change"])
    def force_settle_action(self, request: HttpRequest, object_id: int) -> HttpResponse:
        hold = self._get_hold(request, object_id)
        try:
            hold.settle(hold.amount_consumed_usd)
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Hold force-settled at current consumed amount.")
        return redirect(reverse("admin:billing_billinghold_change", args=[object_id]))

    def _get_hold(self, request: HttpRequest, object_id: int | str) -> BillingHold:
        if not self.has_change_permission(request):
            raise PermissionDenied
        hold = self.get_object(request, str(object_id))
        if hold is None:
            raise Http404("Billing hold does not exist.")
        return cast("BillingHold", hold)
