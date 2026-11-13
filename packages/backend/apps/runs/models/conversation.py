from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import TimestampedModel


class ConversationQuerySet(models.QuerySet["Conversation"]):
    def for_workspace(self, workspace_id: int) -> ConversationQuerySet:
        return self.filter(workspace_id=workspace_id)

    def for_agent(self, agent_id: int) -> ConversationQuerySet:
        return self.filter(agent_id=agent_id)

    def for_end_user(self, end_user_id: int) -> ConversationQuerySet:
        return self.filter(end_user_id=end_user_id)


class Conversation(TimestampedModel):
    conversation_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    agent = models.ForeignKey(
        "agents.Agent",
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    end_user = models.ForeignKey(
        "end_users.EndUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    title = models.CharField(max_length=512, blank=True, default="")

    history = HistoricalRecords()
    objects = ConversationQuerySet.as_manager()

    class Meta:
        db_table = "runs_conversation"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Conversation {self.conversation_uid}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        errors = self._workspace_scope_errors()
        if errors:
            raise ValidationError(errors)

    @classmethod
    def list_for_workspace(
        cls,
        workspace_id: int,
        *,
        agent_id: int | None = None,
    ) -> ConversationQuerySet:
        qs = cls.objects.for_workspace(workspace_id).select_related("agent", "end_user")
        if agent_id is not None:
            qs = qs.for_agent(agent_id)
        return qs

    @classmethod
    def get_for_workspace(
        cls,
        workspace_id: int,
        pk: int,
    ) -> Conversation | None:
        return (
            cls.objects.for_workspace(workspace_id)
            .select_related(
                "agent",
                "end_user",
            )
            .filter(pk=pk)
            .first()
        )

    @classmethod
    def get_by_uid(
        cls,
        workspace_id: int,
        conversation_uid: uuid.UUID,
    ) -> Conversation | None:
        return (
            cls.objects.for_workspace(workspace_id)
            .select_related(
                "agent",
                "end_user",
            )
            .filter(conversation_uid=conversation_uid)
            .first()
        )

    def _workspace_scope_errors(self) -> dict[str, str]:
        errors = {}
        if self.agent_id and self.workspace_id != self.agent.workspace_id:
            errors["agent"] = "Agent must belong to the conversation workspace."
        if self.end_user_id and self.end_user and self.workspace_id != self.end_user.workspace_id:
            errors["end_user"] = "End user must belong to the conversation workspace."
        return errors
