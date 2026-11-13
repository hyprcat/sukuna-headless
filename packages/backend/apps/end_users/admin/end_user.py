from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, StackedInline
from unfold.decorators import action

from apps.end_users.models import ControlProfile, EndUser

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


class ControlProfileInlineForm(forms.ModelForm):
    class Meta:
        model = ControlProfile
        fields = (
            "credits",
            "credit_grant_per_period",
            "run_count_limit",
            "run_count_period",
            "runs_used_in_period",
            "sandbox_time_seconds",
            "concurrency_max",
            "model_tier",
            "allowed_tools",
            "allowed_knowledge",
            "credit_refresh_schedule",
            "next_credit_refresh_at",
        )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        workspace_id = self._workspace_id()
        if workspace_id is not None:
            self._validate_workspace("allowed_tools", cleaned.get("allowed_tools"), workspace_id)
            self._validate_workspace(
                "allowed_knowledge", cleaned.get("allowed_knowledge"), workspace_id
            )
        return cleaned

    def _workspace_id(self) -> int | None:
        if self.instance.end_user_id is None:
            return None
        return int(self.instance.end_user.workspace_id)

    def _validate_workspace(self, field: str, items: Any, workspace_id: int) -> None:
        if items is not None and items.exclude(workspace_id=workspace_id).exists():
            raise forms.ValidationError(
                {field: "Access assignments must belong to the end user's workspace."}
            )


class ControlProfileInline(StackedInline):
    model = ControlProfile
    form = ControlProfileInlineForm
    extra = 0
    max_num = 1
    readonly_fields = ("runs_used_in_period", "next_credit_refresh_at", "created_at", "updated_at")
    filter_horizontal = ("allowed_tools", "allowed_knowledge")
    fieldsets = (
        (
            "Credits",
            {
                "fields": (
                    "credits",
                    "credit_grant_per_period",
                    "credit_refresh_schedule",
                    "next_credit_refresh_at",
                )
            },
        ),
        (
            "Run limits",
            {
                "fields": (
                    "run_count_limit",
                    "run_count_period",
                    "runs_used_in_period",
                    "sandbox_time_seconds",
                    "concurrency_max",
                )
            },
        ),
        ("Model", {"fields": ("model_tier",)}),
        ("Access", {"fields": ("allowed_tools", "allowed_knowledge")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def formfield_for_manytomany(
        self, db_field: Any, request: HttpRequest, **kwargs: Any
    ) -> forms.Field | None:
        if db_field.name in {"allowed_tools", "allowed_knowledge"}:
            workspace_id = self._workspace_id_from_request(request)
            if workspace_id:
                kwargs["queryset"] = db_field.remote_field.model.objects.filter(
                    workspace_id=workspace_id
                )
        field: forms.Field | None = super().formfield_for_manytomany(db_field, request, **kwargs)
        return field

    def _workspace_id_from_request(self, request: HttpRequest) -> str | int | None:
        posted = request.POST.get("workspace")
        if posted:
            return posted
        resolver_match = getattr(request, "resolver_match", None)
        if resolver_match is None:
            return None
        object_id = resolver_match.kwargs.get("object_id")
        if object_id is None:
            return None
        return EndUser.objects.filter(pk=object_id).values_list("workspace_id", flat=True).first()


@admin.register(EndUser)
class EndUserAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "external_user_id",
        "workspace",
        "display_name",
        "tier_label",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "tier_label")
    search_fields = ("external_user_id", "display_name", "workspace__name", "workspace__slug")
    autocomplete_fields = ("workspace",)
    readonly_fields = ("deactivated_at", "created_at", "updated_at")
    inlines = (ControlProfileInline,)
    actions_list = (
        "deactivate_end_users",
        "activate_end_users",
        "refresh_credits_now",
        "override_credits",
        "reset_run_count",
    )
    actions = (
        "deactivate_end_users",
        "activate_end_users",
        "refresh_credits_now",
        "override_credits",
        "reset_run_count",
    )

    fieldsets = (
        (None, {"fields": ("workspace", "external_user_id", "display_name", "tier_label")}),
        ("Metadata", {"fields": ("metadata",)}),
        ("Status", {"fields": ("is_active", "deactivated_at")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    @action(description="Deactivate end users", icon="block")
    def deactivate_end_users(self, request: HttpRequest, queryset: QuerySet[EndUser]) -> None:
        for end_user in queryset.iterator(chunk_size=200):
            end_user.deactivate()
        self.message_user(request, "Selected end users were deactivated.", messages.SUCCESS)

    @action(description="Activate end users", icon="check_circle")
    def activate_end_users(self, request: HttpRequest, queryset: QuerySet[EndUser]) -> None:
        for end_user in queryset.iterator(chunk_size=200):
            end_user.activate()
        self.message_user(request, "Selected end users were activated.", messages.SUCCESS)

    @action(description="Refresh credits now", icon="account_balance_wallet")
    def refresh_credits_now(self, request: HttpRequest, queryset: QuerySet[EndUser]) -> None:
        for end_user in queryset.select_related("profile").iterator(chunk_size=200):
            end_user.refresh_credits()
        self.message_user(request, "Credit refresh completed.", messages.SUCCESS)

    @action(description="Override credits to grant amount", icon="edit")
    def override_credits(self, request: HttpRequest, queryset: QuerySet[EndUser]) -> None:
        count = 0
        for eu in queryset.select_related("profile").iterator(chunk_size=200):
            p = eu.profile
            p.credits = p.credit_grant_per_period
            p.save(update_fields=("credits", "updated_at"))
            count += 1
        self.message_user(request, f"Credits overridden for {count} end user(s).", messages.SUCCESS)

    @action(description="Reset run count", icon="restart_alt")
    def reset_run_count(self, request: HttpRequest, queryset: QuerySet[EndUser]) -> None:
        count = 0
        for eu in queryset.select_related("profile").iterator(chunk_size=200):
            eu.profile.runs_used_in_period = 0
            eu.profile.save(update_fields=("runs_used_in_period", "updated_at"))
            count += 1
        self.message_user(request, f"Run count reset for {count} end user(s).", messages.SUCCESS)
