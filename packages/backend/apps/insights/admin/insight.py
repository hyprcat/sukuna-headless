from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.shortcuts import redirect
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.core.exceptions import Conflict
from apps.insights.models import Insight

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


@admin.register(Insight)
class InsightAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("title", "workspace", "category", "status", "created_at")
    list_filter = (
        "status",
        "category",
        ("workspace", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("title", "body", "workspace__name")
    autocomplete_fields = ("workspace",)
    readonly_fields = ("created_at", "updated_at", "dismissed_at", "pinned_at", "dismissed_by")

    fieldsets = (
        (None, {"fields": ("workspace", "title", "category")}),
        ("Content", {"fields": ("body",)}),
        (
            "Affected entities",
            {"fields": ("affected_agent_ids", "affected_run_ids", "affected_end_user_ids")},
        ),
        ("Status", {"fields": ("status", "pinned_at", "dismissed_at", "dismissed_by")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    actions_detail = ("dismiss_insight", "pin_insight", "unpin_insight")

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @action(description="Dismiss insight", permissions=["change"])
    def dismiss_insight(self, request: HttpRequest, object_id: int) -> HttpResponse:
        insight = Insight.objects.get(pk=object_id)
        user_id = request.user.pk
        if user_id is None:
            messages.error(request, "User account is required.")
            return redirect("admin:insights_insight_change", object_id)
        try:
            insight.dismiss(user_id=user_id)
            messages.success(request, f"Insight {insight.pk!r} dismissed.")
        except Conflict as exc:
            messages.warning(request, str(exc))
        return redirect("admin:insights_insight_change", object_id)

    @action(description="Pin insight", permissions=["change"])
    def pin_insight(self, request: HttpRequest, object_id: int) -> HttpResponse:
        insight = Insight.objects.get(pk=object_id)
        try:
            insight.pin()
            messages.success(request, f"Insight {insight.pk!r} pinned.")
        except Conflict as exc:
            messages.warning(request, str(exc))
        return redirect("admin:insights_insight_change", object_id)

    @action(description="Unpin insight", permissions=["change"])
    def unpin_insight(self, request: HttpRequest, object_id: int) -> HttpResponse:
        insight = Insight.objects.get(pk=object_id)
        try:
            insight.unpin()
            messages.success(request, f"Insight {insight.pk!r} unpinned.")
        except Conflict as exc:
            messages.warning(request, str(exc))
        return redirect("admin:insights_insight_change", object_id)
