from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import Action
from apps.core.events import record_event
from apps.core.exceptions import NotFound
from apps.core.models import TimestampedModel
from apps.policies.schemas import PolicyFormat

if TYPE_CHECKING:
    from apps.workspaces.models.member import WorkspaceMember


class Policy(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="policies",
    )
    name = models.CharField(max_length=160)
    action_restrictions = models.JSONField(
        default=list,
        blank=True,
        help_text="Restrictions on what actions the agent may perform.",
    )
    domain_restrictions = models.JSONField(
        default=list,
        blank=True,
        help_text="Restrictions on which APIs or tools the agent may use.",
    )
    output_restrictions = models.JSONField(
        default=list,
        blank=True,
        help_text="Restrictions on agent output format, length, or content.",
    )
    history = HistoricalRecords()

    class Meta:
        db_table = "policies_policy"
        ordering = ("name",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "name")),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Workspace-scoped queries
    # ------------------------------------------------------------------

    @classmethod
    def for_workspace(cls, workspace_id: int) -> models.QuerySet[Policy]:
        return cls.objects.filter(workspace_id=workspace_id)

    @classmethod
    def get_for_workspace(cls, workspace_id: int, pk: object) -> Policy | None:
        return cls.objects.filter(workspace_id=workspace_id, pk=pk).first()

    @classmethod
    def get_for_workspace_or_raise(cls, workspace_id: int, pk: object) -> Policy:
        try:
            return cls.objects.get(pk=pk, workspace_id=workspace_id)
        except cls.DoesNotExist as exc:
            raise NotFound("Policy not found.") from exc

    @classmethod
    def create_for_workspace(
        cls,
        workspace_id: int,
        *,
        name: str,
        action_restrictions: list[str] | None = None,
        domain_restrictions: list[str] | None = None,
        output_restrictions: list[str] | None = None,
    ) -> Policy:
        policy = cls.objects.create(
            workspace_id=workspace_id,
            name=name,
            action_restrictions=action_restrictions or [],
            domain_restrictions=domain_restrictions or [],
            output_restrictions=output_restrictions or [],
        )
        policy._emit_event("policy_created")
        return policy

    def update(
        self,
        *,
        name: str | None = None,
        action_restrictions: list[str] | None = None,
        domain_restrictions: list[str] | None = None,
        output_restrictions: list[str] | None = None,
    ) -> None:
        with transaction.atomic():
            changed: list[str] = []
            if name is not None:
                self.name = name
                changed.append("name")
            if action_restrictions is not None:
                self.action_restrictions = action_restrictions
                changed.append("action_restrictions")
            if domain_restrictions is not None:
                self.domain_restrictions = domain_restrictions
                changed.append("domain_restrictions")
            if output_restrictions is not None:
                self.output_restrictions = output_restrictions
                changed.append("output_restrictions")
            if changed:
                self.save(update_fields=[*changed, "updated_at"])
                self._emit_event("policy_updated")

    def can_be_edited_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.POLICIES_WRITE)

    def _emit_event(self, name: str) -> None:
        record_event(
            name,
            distinct_id=str(self.workspace_id),
            properties={"policy_id": str(self.pk), "policy_name": self.name},
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def clean(self) -> None:
        fmt = PolicyFormat()
        for field_name in ("action_restrictions", "domain_restrictions", "output_restrictions"):
            self._validate_restriction_list(field_name, fmt)
        self._validate_assembled_length(fmt)

    def _validate_restriction_list(self, field_name: str, fmt: PolicyFormat) -> None:
        value = getattr(self, field_name)
        if not isinstance(value, list):
            raise ValidationError({field_name: "Must be a list of strings."})
        if len(value) > fmt.max_restrictions_per_list:
            raise ValidationError(
                {field_name: f"At most {fmt.max_restrictions_per_list} entries allowed."}
            )
        for idx, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                raise ValidationError({field_name: f"Entry {idx} must be a non-empty string."})
            if len(item) > fmt.max_restriction_length:
                raise ValidationError(
                    {field_name: f"Entry {idx} exceeds {fmt.max_restriction_length} characters."}
                )

    def _validate_assembled_length(self, fmt: PolicyFormat) -> None:
        block = self.as_system_prompt_block()
        if len(block) > fmt.max_prompt_block_length:
            raise ValidationError(
                f"Assembled policy block is {len(block)} characters; "
                f"maximum is {fmt.max_prompt_block_length}."
            )

    def as_system_prompt_block(self) -> str:
        fmt = PolicyFormat()
        sections: list[str] = []
        self._append_section(sections, fmt.action_header, self.action_restrictions)
        self._append_section(sections, fmt.domain_header, self.domain_restrictions)
        self._append_section(sections, fmt.output_header, self.output_restrictions)
        return "\n\n".join(sections)

    @staticmethod
    def _append_section(sections: list[str], header: str, items: list[str]) -> None:
        if not items:
            return
        lines = [f"## {header}"] + [f"- {item}" for item in items]
        sections.append("\n".join(lines))
