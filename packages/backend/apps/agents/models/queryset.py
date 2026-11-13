from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

from apps.core.exceptions import NotFound

if TYPE_CHECKING:
    from apps.agents.models.agent import Agent


class ModelTier(models.TextChoices):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class AgentQuerySet(models.QuerySet["Agent"]):
    def for_workspace(self, workspace_id: int, *, is_active: bool | None = None) -> AgentQuerySet:
        qs = self.filter(workspace_id=workspace_id)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    def get_for_workspace(self, workspace_id: int, pk: int | str) -> Agent | None:
        return (
            self.filter(workspace_id=workspace_id, pk=pk)
            .annotate(
                tools_count=models.Count("tools", distinct=True),
                knowledge_count=models.Count("knowledge_bases", distinct=True),
            )
            .first()
        )

    def get_for_workspace_or_raise(self, workspace_id: int, pk: int | str) -> Agent:
        try:
            return self.get(pk=pk, workspace_id=workspace_id)
        except self.model.DoesNotExist as exc:
            raise NotFound("Agent not found.") from exc

    def create_for_workspace(
        self,
        workspace_id: int,
        *,
        name: str,
        description: str = "",
        system_prompt: str = "",
        default_model_tier: str = "free",
        webhook_url: str = "",
    ) -> Agent:
        return self.create(
            workspace_id=workspace_id,
            name=name,
            description=description,
            system_prompt=system_prompt,
            default_model_tier=default_model_tier,
            webhook_url=webhook_url,
        )
