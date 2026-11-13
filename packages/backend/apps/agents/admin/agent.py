from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from apps.agents.models import Agent
from apps.agents.schemas import AgentFormat

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


class AgentAdminForm(forms.ModelForm):
    class Meta:
        model = Agent
        fields = (
            "workspace",
            "name",
            "description",
            "system_prompt",
            "default_model_tier",
            "webhook_url",
            "tools",
            "knowledge_bases",
            "policy_override",
            "is_active",
        )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        workspace = cleaned.get("workspace")
        self._validate_workspace_assignments(cleaned, workspace)
        self._validate_assignment_caps(cleaned)
        return cleaned

    def _validate_workspace_assignments(self, cleaned: dict[str, Any], workspace: Any) -> None:
        if workspace is None:
            return
        self._validate_assignment_workspace("tools", cleaned.get("tools"), workspace.pk)
        self._validate_assignment_workspace(
            "knowledge_bases", cleaned.get("knowledge_bases"), workspace.pk
        )

    def _validate_assignment_workspace(self, field: str, items: Any, workspace_id: int) -> None:
        if items is not None and items.exclude(workspace_id=workspace_id).exists():
            raise forms.ValidationError({field: "Assignments must belong to the agent workspace."})

    def _validate_assignment_caps(self, cleaned: dict[str, Any]) -> None:
        fmt = AgentFormat()
        self._validate_assignment_count("tools", cleaned.get("tools"), fmt.max_tools_per_agent)
        self._validate_assignment_count(
            "knowledge_bases", cleaned.get("knowledge_bases"), fmt.max_knowledge_per_agent
        )

    def _validate_assignment_count(self, field: str, items: Any, cap: int) -> None:
        if items is not None and items.count() > cap:
            raise forms.ValidationError({field: f"Select at most {cap} items."})


@admin.register(Agent)
class AgentAdmin(SimpleHistoryAdmin, ModelAdmin):
    form = AgentAdminForm
    list_display = ("name", "workspace", "default_model_tier", "is_active", "created_at")
    list_filter = (
        "is_active",
        "default_model_tier",
        ("workspace", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("name", "workspace__name", "workspace__slug")
    autocomplete_fields = ("workspace", "policy_override")
    filter_horizontal = ("tools", "knowledge_bases")
    readonly_fields = ("created_at", "updated_at", "deactivated_at")

    fieldsets = (
        (None, {"fields": ("workspace", "name", "description")}),
        ("Configuration", {"fields": ("system_prompt", "default_model_tier", "webhook_url")}),
        ("Assignments", {"fields": ("tools", "knowledge_bases", "policy_override")}),
        ("Status", {"fields": ("is_active",)}),
        ("Audit", {"fields": ("created_at", "updated_at", "deactivated_at")}),
    )

    actions_detail = ("activate_agent", "deactivate_agent", "clone_agent")

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def formfield_for_manytomany(
        self, db_field: Any, request: HttpRequest, **kwargs: Any
    ) -> forms.Field | None:
        if db_field.name in {"tools", "knowledge_bases"}:
            workspace_id = self._workspace_id_from_request(request)
            if workspace_id:
                kwargs["queryset"] = db_field.remote_field.model.objects.filter(
                    workspace_id=workspace_id
                )
        field: forms.Field | None = super().formfield_for_manytomany(db_field, request, **kwargs)
        return field

    @action(description="Activate agent", permissions=["change"])
    def activate_agent(self, request: HttpRequest, object_id: int) -> HttpResponse:
        Agent.objects.get(pk=object_id).activate()
        return redirect("admin:agents_agent_change", object_id)

    @action(description="Deactivate agent", permissions=["change"])
    def deactivate_agent(self, request: HttpRequest, object_id: int) -> HttpResponse:
        Agent.objects.get(pk=object_id).deactivate()
        return redirect("admin:agents_agent_change", object_id)

    @action(description="Clone with new name", icon="content_copy", permissions=["change"])
    def clone_agent(self, request: HttpRequest, object_id: int) -> HttpResponse:
        agent = Agent.objects.get(pk=object_id)
        clone = agent.clone(self._available_copy_name(agent))
        messages.success(request, f"Cloned as {clone.name!r}.")
        return redirect("admin:agents_agent_change", clone.pk)

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
        return Agent.objects.filter(pk=object_id).values_list("workspace_id", flat=True).first()

    def _available_copy_name(self, agent: Agent) -> str:
        first = f"{agent.name} (copy)"
        existing = set(
            Agent.objects.filter(
                workspace_id=agent.workspace_id, name__startswith=first
            ).values_list("name", flat=True)
        )
        if first not in existing:
            return first
        return self._numbered_copy_name(first, existing)

    def _numbered_copy_name(self, first: str, existing: set[str]) -> str:
        index = 2
        while True:
            candidate = f"{first} {index}"
            if candidate not in existing:
                return candidate
            index += 1
