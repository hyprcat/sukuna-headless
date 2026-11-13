from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import Action
from apps.core.errors import UserError
from apps.core.events import record_event
from apps.core.exceptions import NotFound
from apps.core.models import TimestampedModel
from apps.end_users.models.profile import ControlProfile
from apps.end_users.schemas import Allowed, Denied
from apps.end_users.schemas.config import EndUserFormat

if TYPE_CHECKING:
    from apps.agents.models import Agent
    from apps.knowledge.models import Knowledge
    from apps.tools.models import Tool
    from apps.workspaces.models.member import WorkspaceMember


class EndUserQuerySet(models.QuerySet["EndUser"]):
    def for_workspace(self, workspace_id: int) -> EndUserQuerySet:
        return self.filter(workspace_id=workspace_id)

    def active(self) -> EndUserQuerySet:
        return self.filter(is_active=True)

    def search(self, query: str) -> EndUserQuerySet:
        return self.filter(Q(external_user_id__icontains=query) | Q(display_name__icontains=query))


class EndUser(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="end_users",
    )
    external_user_id = models.CharField(
        max_length=255,
        help_text="Opaque identifier from the developer's auth system.",
    )
    display_name = models.CharField(max_length=160, blank=True, default="")
    tier_label = models.CharField(max_length=40, blank=True, default="")
    metadata = models.JSONField(
        default=dict, blank=True, help_text="Developer-defined custom fields."
    )
    is_active = models.BooleanField(default=True, db_index=True)
    deactivated_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()
    objects = EndUserQuerySet.as_manager()

    class Meta:
        db_table = "end_users_enduser"
        ordering = ("external_user_id",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("workspace", "external_user_id"),
                name="end_users_workspace_ext_user_id_uniq",
            ),
            models.CheckConstraint(
                condition=~Q(external_user_id=""),
                name="end_users_external_user_id_non_empty",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "is_active")),
        ]

    def __str__(self) -> str:
        return self.display_name or self.external_user_id

    def clean(self) -> None:
        self._validate_metadata()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def check_can_run(
        self,
        agent: Agent,
        requested_tools: list[Tool],
        requested_knowledge: list[Knowledge],
        *,
        active_run_count: int = 0,
    ) -> Allowed | Denied:
        if not self.is_active:
            return Denied(reason=UserError.PERMISSION_DENIED)
        if agent.workspace_id != self.workspace_id:
            return Denied(reason=UserError.PERMISSION_DENIED)
        return self._profile_run_check(
            requested_tools=requested_tools,
            requested_knowledge=requested_knowledge,
            active_run_count=active_run_count,
        )

    def _profile_run_check(
        self,
        *,
        requested_tools: list[Tool],
        requested_knowledge: list[Knowledge],
        active_run_count: int,
    ) -> Allowed | Denied:
        profile = self.profile
        denial = (
            self._check_workspace_wallet()
            or self._check_credits(profile)
            or self._check_run_count(profile)
            or self._check_concurrency(profile, active_run_count)
            or self._check_tools(profile, requested_tools)
            or self._check_knowledge(profile, requested_knowledge)
        )
        return denial if denial is not None else Allowed(model_tier=profile.model_tier)

    def refresh_credits(self) -> None:
        with transaction.atomic():
            p = self._locked_profile()
            if not p.refresh_is_due():
                return
            p.apply_credit_refresh()

    def activate(self) -> None:
        if self.is_active:
            return
        self.is_active = True
        self.deactivated_at = None
        self.save(update_fields=("is_active", "deactivated_at", "updated_at"))
        self._emit_event("end_user_activated")

    def deactivate(self) -> None:
        if not self.is_active:
            return
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.save(update_fields=("is_active", "deactivated_at", "updated_at"))
        self._emit_event("end_user_deactivated")

    @classmethod
    def create_with_profile(
        cls,
        workspace_id: int,
        *,
        external_user_id: str,
        display_name: str = "",
        tier_label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> EndUser:
        with transaction.atomic():
            eu = cls.objects.create(
                workspace_id=workspace_id,
                external_user_id=external_user_id,
                display_name=display_name,
                tier_label=tier_label,
                metadata=metadata or {},
            )
            ControlProfile.objects.create(end_user=eu)
            return eu

    def update(
        self,
        *,
        display_name: str | None = None,
        tier_label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        changed: list[str] = []
        for field, value in (
            ("display_name", display_name),
            ("tier_label", tier_label),
            ("metadata", metadata),
        ):
            if value is not None:
                setattr(self, field, value)
                changed.append(field)
        if changed:
            self.save(update_fields=[*changed, "updated_at"])

    @classmethod
    def for_workspace(
        cls,
        workspace_id: int,
        *,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> EndUserQuerySet:
        qs = cls.objects.select_related("profile").filter(workspace_id=workspace_id)
        if search is not None:
            qs = qs.search(search)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    @classmethod
    def get_for_workspace(cls, workspace_id: int, pk: int | str) -> EndUser | None:
        qs = cls.objects.select_related("profile")
        return qs.filter(workspace_id=workspace_id, pk=pk).first()

    @classmethod
    def get_for_workspace_or_raise(cls, workspace_id: int, pk: int | str) -> EndUser:
        try:
            return cls.objects.select_related("profile").get(pk=pk, workspace_id=workspace_id)
        except cls.DoesNotExist as exc:
            raise NotFound("End user not found.") from exc

    def can_be_edited_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.END_USERS_WRITE)

    def can_be_viewed_by(self, member: WorkspaceMember) -> bool:
        return member.workspace_id == self.workspace_id and member.can(Action.END_USERS_READ)

    def _check_workspace_wallet(self) -> Denied | None:
        try:
            available = self.workspace.wallet.available()
        except ObjectDoesNotExist:
            return Denied(reason=UserError.BILLING_ERROR)
        if available <= 0:
            return Denied(reason=UserError.BILLING_ERROR)
        return None

    def _check_credits(self, p: ControlProfile) -> Denied | None:
        if p.credits <= 0:
            return Denied(reason=UserError.INSUFFICIENT_CREDITS)
        return None

    def _check_run_count(self, p: ControlProfile) -> Denied | None:
        if p.run_count_limit is None:
            return None
        effective = self._effective_runs_used(p)
        if effective >= p.run_count_limit:
            return Denied(reason=UserError.RUN_LIMIT_EXCEEDED)
        return None

    def _effective_runs_used(self, p: ControlProfile) -> int:
        if p.next_credit_refresh_at and p.next_credit_refresh_at <= timezone.now():
            return 0
        return p.runs_used_in_period

    def _check_concurrency(self, p: ControlProfile, active: int) -> Denied | None:
        if p.concurrency_max is None:
            return None
        if active >= p.concurrency_max:
            return Denied(reason=UserError.CONCURRENCY_CAP)
        return None

    def _check_tools(self, p: ControlProfile, requested: list[Tool]) -> Denied | None:
        if self._tool_request_denied(p, requested):
            return Denied(reason=UserError.TOOL_NOT_ALLOWED)
        return None

    def _check_knowledge(self, p: ControlProfile, requested: list[Knowledge]) -> Denied | None:
        if self._knowledge_request_denied(p, requested):
            return Denied(reason=UserError.KNOWLEDGE_NOT_ALLOWED)
        return None

    def _tool_request_denied(self, p: ControlProfile, requested: list[Tool]) -> bool:
        if not requested:
            return False
        if any(t.workspace_id != self.workspace_id for t in requested):
            return True
        allowed = set(p.allowed_tools.values_list("pk", flat=True))
        return bool(allowed and not {t.pk for t in requested} <= allowed)

    def _knowledge_request_denied(self, p: ControlProfile, requested: list[Knowledge]) -> bool:
        if not requested:
            return False
        if any(kb.workspace_id != self.workspace_id for kb in requested):
            return True
        allowed = set(p.allowed_knowledge.values_list("pk", flat=True))
        return bool(allowed and not {kb.pk for kb in requested} <= allowed)

    def _validate_metadata(self) -> None:
        fmt = EndUserFormat()
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Must be a JSON object."})
        if len(json.dumps(self.metadata).encode()) > fmt.max_metadata_bytes:
            raise ValidationError({"metadata": f"Exceeds {fmt.max_metadata_bytes} bytes."})

    def _locked_profile(self) -> ControlProfile:
        return ControlProfile.objects.select_for_update().get(end_user_id=self.pk)

    def _emit_event(self, name: str, extra: dict[str, object] | None = None) -> None:
        props: dict[str, object] = {
            "end_user_id": str(self.pk),
            "external_user_id": self.external_user_id,
        }
        if extra:
            props.update(extra)
        record_event(name, distinct_id=str(self.workspace_id), properties=props)
