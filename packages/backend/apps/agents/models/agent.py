from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Protocol, cast

from django.db import IntegrityError, models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import Action
from apps.agents.models.queryset import AgentQuerySet, ModelTier
from apps.agents.models.validators import validate_agent
from apps.agents.schemas import AgentFormat
from apps.core.events import record_event
from apps.core.exceptions import Conflict, NotFound
from apps.core.models import TimestampedModel
from apps.policies.models import Policy

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.knowledge.models import Knowledge
    from apps.tools.models import Tool
    from apps.workspaces.models.member import WorkspaceMember


class _AgentRelationManager(Protocol):
    def filter(self, **kwargs: object) -> QuerySet[models.Model]: ...

    def add(self, *objs: object) -> None: ...

    def remove(self, *objs: object) -> None: ...

    def count(self) -> int: ...


class Agent(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="agents",
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    system_prompt = models.TextField(
        blank=True,
        default="",
        help_text="Base instructions injected into every run.",
    )
    default_model_tier = models.CharField(
        max_length=20,
        choices=ModelTier,
        default=ModelTier.FREE,
    )
    tools = models.ManyToManyField(
        "tools.Tool",
        blank=True,
        related_name="agents",
    )
    knowledge_bases = models.ManyToManyField(
        "knowledge.Knowledge",
        blank=True,
        related_name="agents",
    )
    policy_override = models.ForeignKey(
        "policies.Policy",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="agents",
        help_text="Overrides workspace-level policies for this agent.",
    )
    webhook_url = models.CharField(
        max_length=2048,
        blank=True,
        default="",
        help_text="URL for webhook-triggered invocations.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    deactivated_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()
    objects = AgentQuerySet.as_manager()

    class Meta:
        db_table = "agents_agent"
        ordering = ("name",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("workspace", "name"),
                name="agents_agent_workspace_name_uniq",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "is_active")),
            models.Index(fields=("workspace", "default_model_tier")),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        validate_agent(self, AgentFormat())

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def activate(self) -> None:
        if self.is_active:
            return
        self.is_active = True
        self.deactivated_at = None
        self.save(update_fields=("is_active", "deactivated_at", "updated_at"))
        self._emit_event("agent_activated")

    def deactivate(self) -> None:
        if not self.is_active:
            return
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.save(update_fields=("is_active", "deactivated_at", "updated_at"))
        self._emit_event("agent_deactivated")

    def rename(self, new_name: str) -> None:
        if not new_name.strip():
            raise Conflict("Agent name must not be blank.")
        dupe = (
            type(self)
            .objects.filter(workspace_id=self.workspace_id, name=new_name)
            .exclude(pk=self.pk)
            .exists()
        )
        if dupe:
            raise Conflict("An agent with this name already exists in the workspace.")
        self.name = new_name
        self.save(update_fields=("name", "updated_at"))

    def update(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        default_model_tier: str | None = None,
        webhook_url: str | None = None,
    ) -> None:
        """Partial update: only provided (non-None) fields are changed."""
        with transaction.atomic():
            if name is not None:
                self.rename(name)
            changed: list[str] = []
            for field, value in (
                ("description", description),
                ("system_prompt", system_prompt),
                ("default_model_tier", default_model_tier),
                ("webhook_url", webhook_url),
            ):
                if value is not None:
                    setattr(self, field, value)
                    changed.append(field)
            if changed:
                self.save(update_fields=[*changed, "updated_at"])

    def assign_tool(self, tool: Tool) -> None:
        agent = self._assign_relation_locked(
            tool,
            relation_name="tools",
            obj_label="tool",
            cap=AgentFormat().max_tools_per_agent,
            cap_label="tools",
        )
        if agent is not None:
            agent._emit_event("agent_tool_assigned", extra={"tool_id": str(tool.pk)})

    def remove_tool(self, tool: Tool) -> None:
        agent = self._remove_relation_locked(tool, relation_name="tools", obj_label="tool")
        if agent is not None:
            agent._emit_event("agent_tool_removed", extra={"tool_id": str(tool.pk)})

    def assign_knowledge(self, kb: Knowledge) -> None:
        agent = self._assign_relation_locked(
            kb,
            relation_name="knowledge_bases",
            obj_label="knowledge base",
            cap=AgentFormat().max_knowledge_per_agent,
            cap_label="knowledge bases",
        )
        if agent is not None:
            agent._emit_event("agent_knowledge_assigned", extra={"knowledge_id": str(kb.pk)})

    def remove_knowledge(self, kb: Knowledge) -> None:
        agent = self._remove_relation_locked(
            kb, relation_name="knowledge_bases", obj_label="knowledge base"
        )
        if agent is not None:
            agent._emit_event("agent_knowledge_removed", extra={"knowledge_id": str(kb.pk)})

    def clone(self, new_name: str) -> Agent:
        self._guard_nonblank_clone_name(new_name)
        try:
            source, clone = self._clone_locked(new_name)
        except IntegrityError as exc:
            raise Conflict("An agent with this name already exists in the workspace.") from exc
        source._emit_event("agent_cloned", extra={"clone_id": str(clone.pk)})
        return clone

    def _clone_locked(self, new_name: str) -> tuple[Agent, Agent]:
        with transaction.atomic():
            source = self._locked_self()
            source._guard_clone_name_available(new_name)
            clone = source._create_clone_row(new_name)
            clone.tools.set(source.tools.all())
            clone.knowledge_bases.set(source.knowledge_bases.all())
            return source, clone

    def _locked_self(self) -> Agent:
        model = type(self)
        try:
            return model.objects.select_for_update().get(pk=self.pk)
        except model.DoesNotExist as exc:
            raise NotFound("Agent not found.") from exc

    def _create_clone_row(self, new_name: str) -> Agent:
        return type(self).objects.create(
            workspace_id=self.workspace_id,
            name=new_name,
            description=self.description,
            system_prompt=self.system_prompt,
            default_model_tier=self.default_model_tier,
            policy_override_id=self.policy_override_id,
            webhook_url=self.webhook_url,
        )

    def _guard_nonblank_clone_name(self, new_name: str) -> None:
        if not new_name.strip():
            raise Conflict("Agent name must not be blank.")

    def _guard_clone_name_available(self, new_name: str) -> None:
        dupe = type(self).objects.filter(workspace_id=self.workspace_id, name=new_name).exists()
        if dupe:
            raise Conflict("An agent with this name already exists in the workspace.")

    def effective_policies(self) -> QuerySet[Policy]:
        if self.policy_override_id is not None:
            return Policy.objects.filter(pk=self.policy_override_id)
        return Policy.objects.filter(workspace_id=self.workspace_id)

    def can_be_edited_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.AGENTS_WRITE)

    def can_be_deleted_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.AGENTS_DELETE)

    def _emit_event(self, name: str, *, extra: dict[str, str] | None = None) -> None:
        props: dict[str, str] = {"agent_id": str(self.pk), "agent_name": self.name}
        if extra:
            props.update(extra)
        record_event(name, distinct_id=str(self.workspace_id), properties=props)

    def _guard_same_workspace(self, obj: Tool | Knowledge, label: str) -> None:
        if obj.workspace_id != self.workspace_id:
            raise Conflict(f"Cannot use a {label} from a different workspace.")

    def _assign_relation_locked(
        self,
        obj: Tool | Knowledge,
        *,
        relation_name: str,
        obj_label: str,
        cap: int,
        cap_label: str,
    ) -> Agent | None:
        with transaction.atomic():
            agent = self._locked_self()
            agent._guard_same_workspace(obj, obj_label)
            manager = agent._relation_manager(relation_name)
            if manager.filter(pk=obj.pk).exists():
                return None
            agent._guard_m2m_cap(manager, cap, cap_label)
            manager.add(obj)
            return agent

    def _remove_relation_locked(
        self, obj: Tool | Knowledge, *, relation_name: str, obj_label: str
    ) -> Agent | None:
        with transaction.atomic():
            agent = self._locked_self()
            agent._guard_same_workspace(obj, obj_label)
            manager = agent._relation_manager(relation_name)
            if not manager.filter(pk=obj.pk).exists():
                return None
            manager.remove(obj)
            return agent

    def _relation_manager(self, relation_name: str) -> _AgentRelationManager:
        return cast("_AgentRelationManager", getattr(self, relation_name))

    @staticmethod
    def _guard_m2m_cap(manager: _AgentRelationManager, cap: int, label: str) -> None:
        if manager.count() >= cap:
            raise Conflict(f"Agent already has the maximum number of {label} ({cap}).")
