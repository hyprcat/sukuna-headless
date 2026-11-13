from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.shortcuts import redirect
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.runs.models import SandboxInstance, SandboxState

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


@admin.register(SandboxInstance)
class SandboxInstanceAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "sandbox_id",
        "workspace",
        "agent",
        "sandbox_state",
        "current_run",
        "created_at",
    )
    list_filter = (
        "sandbox_state",
        ("workspace", admin.RelatedOnlyFieldListFilter),
        ("agent", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("sandbox_id", "workspace__name", "workspace__slug")
    autocomplete_fields = ("workspace", "agent", "current_run")
    readonly_fields = (
        "sandbox_id",
        "sandbox_url",
        "sandbox_state",
        "current_run",
        "boot_started_at",
        "boot_completed_at",
        "last_run_finished_at",
        "delayed_termination_at",
        "pause_count",
        "resume_count",
        "conversation_id",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("sandbox_id", "workspace", "agent", "conversation_id")}),
        ("State", {"fields": ("sandbox_state", "sandbox_url", "current_run")}),
        (
            "Lifecycle",
            {
                "fields": (
                    "boot_started_at",
                    "boot_completed_at",
                    "last_run_finished_at",
                    "delayed_termination_at",
                    "pause_count",
                    "resume_count",
                )
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    actions_detail = ("terminate_sandbox",)

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @action(description="Terminate sandbox", permissions=["change"])
    def terminate_sandbox(self, request: HttpRequest, object_id: int) -> HttpResponse:
        instance = SandboxInstance.objects.get(pk=object_id)
        if instance.sandbox_state == SandboxState.TERMINATED:
            messages.warning(request, f"Sandbox {instance.sandbox_id} is already terminated.")
        else:
            instance.mark_terminated()
            messages.success(request, f"Sandbox {instance.sandbox_id} terminated.")
        return redirect("admin:runs_sandboxinstance_change", object_id)
