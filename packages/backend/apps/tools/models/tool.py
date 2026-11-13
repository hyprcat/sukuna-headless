from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import Action
from apps.core.events import record_event
from apps.core.exceptions import Conflict, NotFound
from apps.core.models import TimestampedModel
from apps.tools.schemas import ToolFormat

if TYPE_CHECKING:
    from apps.workspaces.models.member import WorkspaceMember


class Tool(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="tools",
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    parameters_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON Schema defining the tool's input parameters.",
    )
    execution_endpoint = models.CharField(
        max_length=2048,
        help_text="URL or route the sandbox calls when executing this tool.",
    )
    is_sensitive = models.BooleanField(
        default=False,
        help_text="Sensitive tools pause execution for end-user approval.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    deactivated_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        db_table = "tools_tool"
        ordering = ("name",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("workspace", "name"),
                name="tools_tool_workspace_name_uniq",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "is_active")),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        fmt = ToolFormat()
        self._validate_description(fmt)
        self._validate_parameters_schema(fmt)
        self._validate_endpoint()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def activate(self) -> None:
        if self.is_active:
            return
        self.is_active = True
        self.deactivated_at = None
        self.save(update_fields=("is_active", "deactivated_at", "updated_at"))
        self._emit_event("tool_activated")

    def deactivate(self) -> None:
        if not self.is_active:
            return
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.save(update_fields=("is_active", "deactivated_at", "updated_at"))
        self._emit_event("tool_deactivated")

    def rename(self, new_name: str) -> None:
        if not new_name.strip():
            raise Conflict("Tool name must not be blank.")
        dupe = (
            type(self)
            .objects.filter(workspace_id=self.workspace_id, name=new_name)
            .exclude(pk=self.pk)
            .exists()
        )
        if dupe:
            raise Conflict("A tool with this name already exists in the workspace.")
        self.name = new_name
        self.save(update_fields=("name", "updated_at"))

    def update(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        parameters_schema: dict[str, Any] | None = None,
        execution_endpoint: str | None = None,
        is_sensitive: bool | None = None,
    ) -> None:
        with transaction.atomic():
            if name is not None:
                self.rename(name)
            changed: list[str] = []
            if description is not None:
                self.description = description
                changed.append("description")
            if parameters_schema is not None:
                self.parameters_schema = parameters_schema
                changed.append("parameters_schema")
            if execution_endpoint is not None:
                self.execution_endpoint = execution_endpoint
                changed.append("execution_endpoint")
            if is_sensitive is not None:
                self.is_sensitive = is_sensitive
                changed.append("is_sensitive")
            if changed:
                self.save(update_fields=[*changed, "updated_at"])

    def validate_params(self, payload: dict[str, Any]) -> list[str]:
        """Validate *payload* against the stored JSON Schema.

        Returns an empty list on success or a list of human-readable
        error messages on failure.  Never raises — callers decide how
        to surface problems.
        """
        if not self.parameters_schema:
            return []
        validator = Draft202012Validator(self.parameters_schema)
        return [e.message for e in validator.iter_errors(payload)]

    @classmethod
    def create_for_workspace(
        cls,
        workspace_id: int,
        *,
        name: str,
        description: str = "",
        parameters_schema: dict[str, Any] | None = None,
        execution_endpoint: str = "",
        is_sensitive: bool = False,
    ) -> Tool:
        return cls.objects.create(
            workspace_id=workspace_id,
            name=name,
            description=description,
            parameters_schema=parameters_schema or {},
            execution_endpoint=execution_endpoint,
            is_sensitive=is_sensitive,
        )

    @classmethod
    def for_workspace(
        cls, workspace_id: int, *, is_active: bool | None = None
    ) -> models.QuerySet[Tool]:
        qs = cls.objects.filter(workspace_id=workspace_id)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    @classmethod
    def get_for_workspace(cls, workspace_id: int, pk: object) -> Tool | None:
        return cls.objects.filter(workspace_id=workspace_id, pk=pk).first()

    @classmethod
    def get_for_workspace_or_raise(cls, workspace_id: int, pk: object) -> Tool:
        try:
            return cls.objects.get(pk=pk, workspace_id=workspace_id)
        except cls.DoesNotExist as exc:
            raise NotFound("Tool not found.") from exc

    def can_be_edited_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.TOOLS_WRITE)

    def _emit_event(self, name: str) -> None:
        record_event(
            name,
            distinct_id=str(self.workspace_id),
            properties={"tool_id": str(self.pk), "tool_name": self.name},
        )

    def _validate_description(self, fmt: ToolFormat) -> None:
        if len(self.description) > fmt.max_description_length:
            raise ValidationError(
                {"description": f"Exceeds {fmt.max_description_length} characters."}
            )

    def _validate_parameters_schema(self, fmt: ToolFormat) -> None:
        if not isinstance(self.parameters_schema, dict):
            raise ValidationError({"parameters_schema": "Must be a JSON object."})
        raw = json.dumps(self.parameters_schema)
        if len(raw.encode()) > fmt.max_parameter_schema_bytes:
            raise ValidationError(
                {"parameters_schema": f"Exceeds {fmt.max_parameter_schema_bytes} bytes."}
            )
        props = self.parameters_schema.get("properties", {})
        if isinstance(props, dict) and len(props) > fmt.max_parameters_keys:
            raise ValidationError(
                {"parameters_schema": f"At most {fmt.max_parameters_keys} parameters allowed."}
            )
        self._validate_schema_is_valid_json_schema()

    def _validate_schema_is_valid_json_schema(self) -> None:
        try:
            Draft202012Validator.check_schema(self.parameters_schema)
        except SchemaError as exc:
            raise ValidationError(
                {"parameters_schema": f"Invalid JSON Schema: {exc.message}"}
            ) from exc

    def _validate_endpoint(self) -> None:
        if not self.execution_endpoint.strip():
            raise ValidationError({"execution_endpoint": "Execution endpoint must not be blank."})
