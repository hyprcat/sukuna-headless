from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.schedules.models import Schedule

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


class ScheduleAdminForm(forms.ModelForm):
    class Meta:
        model = Schedule
        fields = (
            "workspace",
            "name",
            "description",
            "agent",
            "target_end_user",
            "prompt",
            "cron_expression",
            "failure_handling",
            "output_routing",
            "status",
        )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        workspace = cleaned.get("workspace")
        if workspace is not None:
            self._validate_workspace("agent", cleaned.get("agent"), workspace.pk)
            self._validate_workspace(
                "target_end_user", cleaned.get("target_end_user"), workspace.pk
            )
        return cleaned

    def _validate_workspace(self, field: str, obj: Any, workspace_id: int) -> None:
        if obj is not None and obj.workspace_id != workspace_id:
            raise forms.ValidationError({field: "Selection must belong to the schedule workspace."})


@admin.register(Schedule)
class ScheduleAdmin(SimpleHistoryAdmin, ModelAdmin):
    form = ScheduleAdminForm
    list_display = (
        "name",
        "workspace",
        "agent",
        "status",
        "cron_expression",
        "next_run_at",
        "consecutive_failures",
    )
    list_filter = (
        "status",
        "failure_handling",
        ("workspace", admin.RelatedOnlyFieldListFilter),
        ("agent", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("name", "workspace__name", "agent__name")
    autocomplete_fields = ("workspace", "agent", "target_end_user")
    readonly_fields = (
        "created_at",
        "updated_at",
        "next_run_at",
        "last_run_at",
        "consecutive_failures",
        "paused_at",
        "disabled_at",
    )

    fieldsets = (
        (None, {"fields": ("workspace", "name", "description")}),
        ("Target", {"fields": ("agent", "target_end_user", "prompt")}),
        ("Timing", {"fields": ("cron_expression", "failure_handling")}),
        ("Output", {"fields": ("output_routing",)}),
        ("Status", {"fields": ("status", "next_run_at", "last_run_at", "consecutive_failures")}),
        ("Audit", {"fields": ("created_at", "updated_at", "paused_at", "disabled_at")}),
    )

    actions_detail = ("run_now", "pause_schedule", "resume_schedule", "disable_schedule")

    def formfield_for_foreignkey(
        self, db_field: Any, request: HttpRequest, **kwargs: Any
    ) -> forms.Field | None:
        if db_field.name in {"agent", "target_end_user"}:
            workspace_id = self._workspace_id_from_request(request)
            if workspace_id:
                kwargs["queryset"] = db_field.remote_field.model.objects.filter(
                    workspace_id=workspace_id
                )
        field: forms.Field | None = super().formfield_for_foreignkey(db_field, request, **kwargs)
        return field

    @action(description="Run now", icon="play_arrow", permissions=["change"])
    def run_now(self, request: HttpRequest, object_id: int) -> HttpResponse:
        from apps.schedules.models.execution import ExecutionOutcome  # noqa: PLC0415
        from apps.schedules.tasks.dispatch import run_now  # noqa: PLC0415

        schedule = Schedule.objects.select_related(
            "workspace__wallet", "agent", "target_end_user"
        ).get(pk=object_id)
        execution = run_now(schedule)
        if execution.outcome == ExecutionOutcome.SUCCESS:
            messages.success(request, "Run started.")
        else:
            reason = execution.skip_reason or execution.error_message
            messages.warning(request, f"Run not started: {reason}")
        return redirect("admin:schedules_schedule_change", object_id)

    @action(description="Pause schedule", permissions=["change"])
    def pause_schedule(self, request: HttpRequest, object_id: int) -> HttpResponse:
        Schedule.objects.get(pk=object_id).pause()
        messages.success(request, "Schedule paused.")
        return redirect("admin:schedules_schedule_change", object_id)

    @action(description="Resume schedule", permissions=["change"])
    def resume_schedule(self, request: HttpRequest, object_id: int) -> HttpResponse:
        Schedule.objects.get(pk=object_id).resume()
        messages.success(request, "Schedule resumed.")
        return redirect("admin:schedules_schedule_change", object_id)

    @action(description="Disable schedule", icon="block", permissions=["change"])
    def disable_schedule(self, request: HttpRequest, object_id: int) -> HttpResponse:
        Schedule.objects.get(pk=object_id).disable()
        messages.success(request, "Schedule disabled.")
        return redirect("admin:schedules_schedule_change", object_id)

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
        return Schedule.objects.filter(pk=object_id).values_list("workspace_id", flat=True).first()
