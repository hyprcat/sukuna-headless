from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action

from apps.workspaces.models import Invitation, Workspace, WorkspaceMember

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


class WorkspaceMemberInline(TabularInline):
    model = WorkspaceMember
    extra = 0
    autocomplete_fields = ("user", "invited_by")
    fields = ("user", "role", "invited_by", "joined_at")
    readonly_fields = ("joined_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[WorkspaceMember]:
        queryset = super().get_queryset(request).select_related("user", "invited_by")
        return cast("QuerySet[WorkspaceMember]", queryset)


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("user", "workspace", "role", "joined_at", "created_at")
    list_filter = ("role", "joined_at")
    search_fields = ("user__email", "workspace__name", "workspace__slug")
    autocomplete_fields = ("workspace", "user", "invited_by")
    list_select_related = ("workspace", "user", "invited_by")
    readonly_fields = ("created_at", "updated_at", "joined_at")

    fieldsets = (
        (None, {"fields": ("workspace", "user", "role", "invited_by")}),
        ("Membership", {"fields": ("joined_at",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Workspace)
class WorkspaceAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("name", "slug", "owner", "billing_email", "suspended_at", "created_at")
    list_filter = ("suspended_at",)
    search_fields = ("name", "slug", "billing_email", "owner__email")
    autocomplete_fields = ("owner",)
    list_select_related = ("owner",)
    readonly_fields = ("created_at", "updated_at", "suspended_at")
    inlines = (WorkspaceMemberInline,)
    actions_list = ("suspend_workspace",)
    actions = ("suspend_workspace",)

    fieldsets = (
        (None, {"fields": ("name", "slug", "owner", "billing_email")}),
        ("Status", {"fields": ("suspended_at",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    @action(description="Suspend workspace", icon="block")
    def suspend_workspace(self, request: HttpRequest, queryset: QuerySet[Workspace]) -> None:
        for workspace in queryset.iterator(chunk_size=200):
            workspace.suspend()
        self.message_user(request, "Selected workspaces were suspended.", messages.SUCCESS)


@admin.register(Invitation)
class InvitationAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ("email", "workspace", "role", "expires_at", "accepted_at", "created_at")
    list_filter = ("role", "accepted_at", "expires_at")
    search_fields = ("email", "workspace__name", "workspace__slug")
    autocomplete_fields = ("workspace",)
    list_select_related = ("workspace",)
    readonly_fields = ("token", "created_at", "updated_at", "accepted_at")

    fieldsets = (
        (None, {"fields": ("workspace", "email", "role")}),
        ("Token", {"fields": ("token", "expires_at", "accepted_at")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
