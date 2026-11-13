from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.shortcuts import redirect
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.tools.models import Tool

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


@admin.register(Tool)
class ToolAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("name", "workspace", "is_active", "is_sensitive", "created_at")
    list_filter = ("is_active", "is_sensitive", ("workspace", admin.RelatedOnlyFieldListFilter))
    search_fields = ("name", "workspace__name", "workspace__slug")
    autocomplete_fields = ("workspace",)
    readonly_fields = ("created_at", "updated_at", "deactivated_at")

    fieldsets = (
        (None, {"fields": ("workspace", "name", "description")}),
        ("Execution", {"fields": ("execution_endpoint", "parameters_schema")}),
        ("Behaviour", {"fields": ("is_sensitive", "is_active")}),
        ("Audit", {"fields": ("created_at", "updated_at", "deactivated_at")}),
    )

    actions_detail = ("activate_tool", "deactivate_tool", "test_endpoint")

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @action(description="Activate tool", permissions=["change"])
    def activate_tool(self, request: HttpRequest, object_id: int) -> HttpResponse:
        Tool.objects.get(pk=object_id).activate()
        return redirect("admin:tools_tool_change", object_id)

    @action(description="Deactivate tool", permissions=["change"])
    def deactivate_tool(self, request: HttpRequest, object_id: int) -> HttpResponse:
        Tool.objects.get(pk=object_id).deactivate()
        return redirect("admin:tools_tool_change", object_id)

    @action(description="Test endpoint", icon="science", permissions=["view"])
    def test_endpoint(self, request: HttpRequest, object_id: int) -> HttpResponse:
        tool = Tool.objects.get(pk=object_id)
        errors = tool.validate_params({})
        if errors:
            self.message_user(request, f"Empty payload fails schema: {errors[0]}", messages.WARNING)
        else:
            self.message_user(request, f"Schema accepts empty payload for {tool.name}.")
        return redirect("admin:tools_tool_change", object_id)
