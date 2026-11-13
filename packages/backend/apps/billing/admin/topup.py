from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import path, reverse
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.billing.models import CreditWallet, Topup
from apps.billing.services.dodo import refund_topup
from apps.core.exceptions import DomainError

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.urls.resolvers import URLPattern


class RefundForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        min_length=4,
        help_text="Why this top-up is being refunded. Recorded in the ledger.",
    )

    def clean_reason(self) -> str:
        return cast("str", self.cleaned_data["reason"]).strip()


@admin.register(Topup)
class TopupAdmin(SimpleHistoryAdmin, ModelAdmin):
    """Filterable by status; row writes happen through the webhook receiver."""

    list_display = (
        "idempotency_key",
        "wallet",
        "amount_usd",
        "currency",
        "status",
        "dodo_payment_id",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("idempotency_key", "dodo_payment_id", "wallet__workspace__slug")
    autocomplete_fields = ("wallet",)
    readonly_fields: ClassVar[tuple[str, ...]] = (
        "wallet",
        "amount_usd",
        "currency",
        "idempotency_key",
        "dodo_payment_id",
        "status",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("wallet", "amount_usd", "currency", "status")}),
        ("Provider", {"fields": ("idempotency_key", "dodo_payment_id")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
    actions_detail = ("refund_topup_action",)

    def get_urls(self) -> list[URLPattern]:
        return [
            path(
                "<path:object_id>/refund/",
                self.admin_site.admin_view(self.refund_view),
                name="billing_topup_refund",
            ),
            *super().get_urls(),
        ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @action(description="Refund this top-up", icon="undo", permissions=["view"])
    def refund_topup_action(self, request: HttpRequest, object_id: int) -> HttpResponse:
        self._require_wallet_change(request)
        return redirect(reverse("admin:billing_topup_refund", args=[object_id]))

    def refund_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        self._require_wallet_change(request)
        topup = self._get_topup(request, object_id)
        form = RefundForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            return self._apply_refund(request, topup, form)
        return render(
            request,
            "admin/billing/topup_refund.html",
            {**self.admin_site.each_context(request), "topup": topup, "form": form},
        )

    def _apply_refund(self, request: HttpRequest, topup: Topup, form: RefundForm) -> HttpResponse:
        try:
            refund_topup(topup, reason=form.cleaned_data["reason"])
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect(request.path)
        messages.success(
            request,
            f"Refund of ${topup.amount_usd} requested — balance will update when Dodo confirms.",
        )
        return redirect(reverse("admin:billing_topup_changelist"))

    def _get_topup(self, request: HttpRequest, object_id: str) -> Topup:
        topup = self.get_object(request, object_id)
        if topup is None:
            raise Http404("Topup does not exist.")
        return cast("Topup", topup)

    @staticmethod
    def _require_wallet_change(request: HttpRequest) -> None:
        opts = CreditWallet._meta
        perm = f"{opts.app_label}.change_{opts.model_name}"
        if not request.user.has_perm(perm):
            raise PermissionDenied
