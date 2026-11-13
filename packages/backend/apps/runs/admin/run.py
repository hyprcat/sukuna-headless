from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.shortcuts import redirect
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.runs.admin.event import RunEventInline
from apps.runs.models import Run

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


@admin.register(Run)
class RunAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("run_uid", "agent", "end_user", "status", "total_cost_usd", "created_at")
    inlines = (RunEventInline,)
    list_filter = (
        "status",
        "is_scheduled",
        ("workspace", admin.RelatedOnlyFieldListFilter),
        ("agent", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("run_uid", "end_user__external_user_id", "agent__name")
    autocomplete_fields = ("workspace", "agent", "end_user")
    readonly_fields = (
        "run_uid",
        "manifest_id",
        "last_callback_at",
        "last_projected_sequence",
        "started_at",
        "finished_at",
        "total_cost_usd",
        "total_tokens",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("workspace", "agent", "end_user", "run_uid", "conversation")}),
        ("Input", {"fields": ("prompt", "is_scheduled")}),
        ("Status", {"fields": ("status", "sandbox_id", "error_message", "summary")}),
        ("Integration", {"fields": ("manifest_id", "last_callback_at", "last_projected_sequence")}),
        ("Usage", {"fields": ("total_cost_usd", "total_tokens")}),
        ("Timestamps", {"fields": ("started_at", "finished_at", "created_at", "updated_at")}),
    )

    actions_detail = ("cancel_run",)

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @action(description="Cancel run", permissions=["change"])
    def cancel_run(self, request: HttpRequest, object_id: int) -> HttpResponse:
        run = Run.objects.get(pk=object_id)
        if run.is_terminal:
            messages.warning(request, f"Run {run.run_uid} is already {run.status}.")
        else:
            run.cancel()
            messages.success(request, f"Run {run.run_uid} cancelled.")
        return redirect("admin:runs_run_change", object_id)
