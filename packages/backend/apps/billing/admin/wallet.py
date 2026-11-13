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

from apps.billing.models import CreditWallet
from apps.billing.schemas import BillingFormat
from apps.core.exceptions import DomainError

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.urls.resolvers import URLPattern


class ManualAdjustmentForm(forms.Form):
    """Mandatory note + signed delta — admins clarify intent on every entry."""

    delta_usd = forms.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
        help_text="Signed delta. Positive credits the wallet, negative claws back.",
    )
    note = forms.CharField(
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        min_length=4,
        error_messages={"required": "Reason is required."},
        help_text="Mandatory. Recorded on the ledger entry and visible in the audit trail.",
    )
    reference = forms.CharField(
        max_length=128,
        error_messages={"required": "Reference is required."},
        help_text="Free-form reference (admin user ID, ticket number, etc.).",
    )

    def clean_reference(self) -> str:
        reference = cast("str", self.cleaned_data["reference"]).strip()
        if not reference:
            raise forms.ValidationError("Reference is required.")
        return reference

    def clean_note(self) -> str:
        note = cast("str", self.cleaned_data["note"]).strip()
        if not note:
            raise forms.ValidationError("Reason is required.")
        return note


@admin.register(CreditWallet)
class CreditWalletAdmin(SimpleHistoryAdmin, ModelAdmin):
    """Read-mostly. Only write path is the manual adjustment detail action."""

    list_display = ("workspace", "balance_usd", "currency", "last_topup_at", "created_at")
    search_fields = ("workspace__slug", "workspace__name")
    autocomplete_fields = ("workspace",)
    readonly_fields: ClassVar[tuple[str, ...]] = (
        "workspace",
        "balance_usd",
        "currency",
        "last_topup_at",
        "created_at",
        "updated_at",
    )
    actions_detail = ("adjust_balance",)

    fieldsets = (
        (None, {"fields": ("workspace",)}),
        ("Balance", {"fields": ("balance_usd", "currency", "last_topup_at")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def get_urls(self) -> list[URLPattern]:
        return [
            path(
                "<path:object_id>/adjust/",
                self.admin_site.admin_view(self.adjust_view),
                name="billing_creditwallet_adjust",
            ),
            *super().get_urls(),
        ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @action(description="Manual adjustment", icon="tune", permissions=["change"])
    def adjust_balance(self, request: HttpRequest, object_id: int) -> HttpResponse:
        return redirect(reverse("admin:billing_creditwallet_adjust", args=[object_id]))

    def adjust_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        wallet = self._adjustment_wallet(request, object_id)
        form = ManualAdjustmentForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            return self._apply_adjustment(request, wallet, form)
        return render(
            request,
            "admin/billing/wallet_adjust.html",
            {**self.admin_site.each_context(request), "wallet": wallet, "form": form},
        )

    def _apply_adjustment(
        self, request: HttpRequest, wallet: CreditWallet, form: ManualAdjustmentForm
    ) -> HttpResponse:
        try:
            wallet.post_adjustment(
                form.cleaned_data["delta_usd"],
                note=form.cleaned_data["note"],
                reference=form.cleaned_data["reference"],
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect(request.path)
        messages.success(request, "Adjustment recorded.")
        return redirect(reverse("admin:billing_creditwallet_change", args=[wallet.pk]))

    def _adjustment_wallet(self, request: HttpRequest, object_id: str) -> CreditWallet:
        wallet = self.get_object(request, object_id)
        if wallet is None:
            raise Http404("Credit wallet does not exist.")
        if not self.has_change_permission(request, wallet):
            raise PermissionDenied
        return cast("CreditWallet", wallet)
