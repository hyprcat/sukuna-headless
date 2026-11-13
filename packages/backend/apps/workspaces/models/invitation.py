from __future__ import annotations

import secrets
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar, cast

from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import models, transaction
from django.utils import timezone
from pydantic import BaseModel, ConfigDict
from simple_history.models import HistoricalRecords

from apps.core.events import record_event
from apps.core.exceptions import Conflict, InvalidInput, NotFound
from apps.core.models import TimestampedModel
from apps.workspaces.models.member import WorkspaceMember, WorkspaceRole

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.accounts.models import User
    from apps.workspaces.models.workspace import Workspace


class InvitationFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    signing_salt: str = "workspaces.invitation"
    expiry_days: int = 7


class Invitation(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=WorkspaceRole, default=WorkspaceRole.VIEWER)
    token = models.TextField(unique=True, blank=True, default="", editable=False)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        db_table = "workspaces_invitation"
        ordering = ("-created_at",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "accepted_at")),
            models.Index(fields=("email", "accepted_at")),
        ]

    def __str__(self) -> str:
        return f"{self.email} invited to {self.workspace}"

    @classmethod
    def build_token(cls, *, workspace_id: int, email: str) -> str:
        payload = {
            "workspace_id": workspace_id,
            "email": email,
            "nonce": secrets.token_urlsafe(16),
        }
        return signing.dumps(payload, salt=InvitationFormat().signing_salt)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = self._normalise_email(self.email)
        if not self.token:
            self.token = self.build_token(workspace_id=self.workspace_id, email=self.email)
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def create_for_workspace(
        cls,
        *,
        workspace: Workspace,
        email: str,
        role: str,
    ) -> Invitation:
        cls._validate_role_input(role)
        normalised = cls._clean_email_input(email)
        with transaction.atomic():
            cls._lock_workspace(workspace)
            cls._delete_expired_duplicate(workspace, normalised)
            cls._guard_no_pending_duplicate(workspace, normalised)
            invitation = cls._create_pending(workspace, normalised, role)
        cls._record_invited(workspace, normalised, role)
        return invitation

    @staticmethod
    def _clean_email_input(email: str) -> str:
        normalised = Invitation._normalise_email(email)
        try:
            validate_email(normalised)
        except DjangoValidationError as exc:
            raise InvalidInput("Enter a valid email address.", field="email") from exc
        return normalised

    @staticmethod
    def _normalise_email(email: str) -> str:
        return (email or "").strip().lower()

    @staticmethod
    def _lock_workspace(workspace: Workspace) -> None:
        workspace.__class__.objects.select_for_update().only("id").get(pk=workspace.pk)

    @classmethod
    def _delete_expired_duplicate(cls, workspace: Workspace, email: str) -> None:
        cls.objects.filter(
            workspace=workspace,
            email__iexact=email,
            accepted_at__isnull=True,
            expires_at__lte=timezone.now(),
        ).delete()

    @staticmethod
    def _validate_role_input(role: str) -> None:
        if role not in WorkspaceRole.values:
            raise InvalidInput("Invalid role.", field="role")

    @classmethod
    def _guard_no_pending_duplicate(cls, workspace: Workspace, email: str) -> None:
        existing = cls.pending_for_workspace(workspace.pk).filter(email__iexact=email).first()
        if existing is not None:
            raise Conflict("A pending invitation already exists for this email.")

    @classmethod
    def _create_pending(cls, workspace: Workspace, email: str, role: str) -> Invitation:
        expires_at = timezone.now() + timedelta(days=InvitationFormat().expiry_days)
        return cls.objects.create(
            workspace=workspace,
            email=email,
            role=role,
            expires_at=expires_at,
        )

    @staticmethod
    def _record_invited(workspace: Workspace, email: str, role: str) -> None:
        record_event(
            "workspace_member_invited",
            distinct_id=str(workspace.pk),
            properties={"email": email, "role": role},
        )

    @classmethod
    def pending_for_workspace(cls, workspace_pk: int) -> QuerySet[Invitation]:
        return cls.objects.filter(
            workspace_id=workspace_pk,
            accepted_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).order_by("-created_at")

    @classmethod
    def get_pending_or_raise(cls, workspace_pk: int, invitation_id: int | str) -> Invitation:
        try:
            inv = cls.objects.get(pk=invitation_id, workspace_id=workspace_pk)
        except (cls.DoesNotExist, ValueError):
            raise NotFound("Invitation not found.") from None
        if not inv.is_pending:
            raise Conflict("Invitation is no longer pending.")
        return inv

    @classmethod
    def get_by_token_or_raise(cls, token: str) -> Invitation:
        try:
            return cls.objects.select_related("workspace").get(token=token)
        except cls.DoesNotExist:
            raise NotFound("Invitation not found or expired.") from None

    @transaction.atomic
    def revoke(self) -> None:
        invitation = self._locked()
        if not invitation.is_pending:
            raise Conflict("Invitation is no longer pending.")
        workspace_id = invitation.workspace_id
        email = invitation.email
        invitation.delete()
        record_event(
            "workspace_invitation_revoked",
            distinct_id=str(workspace_id),
            properties={"email": email},
        )

    @property
    def is_pending(self) -> bool:
        return self.accepted_at is None and self.expires_at > timezone.now()

    @transaction.atomic
    def accept(self, user: User) -> WorkspaceMember:
        invitation = self._locked()
        if not invitation.is_pending:
            raise Conflict("Invitation is no longer pending.")
        invitation._validate_user(user)
        member = invitation._accept_member(user)
        invitation._mark_accepted()
        self.accepted_at = invitation.accepted_at
        record_event(
            "workspace_invitation_accepted",
            distinct_id=str(invitation.workspace_id),
            properties={"user_id": user.pk, "email": invitation.email},
        )
        return member

    def _locked(self) -> Invitation:
        if self.pk is None:
            raise Conflict("Invitation must be saved before changing state.")
        try:
            return (
                type(self).objects.select_for_update().select_related("workspace").get(pk=self.pk)
            )
        except type(self).DoesNotExist:
            raise Conflict("Invitation is no longer pending.") from None

    def _validate_user(self, user: User) -> None:
        if user.email.lower() != self.email.lower():
            raise Conflict("Invitation email does not match this user.")
        payload = self._token_payload()
        if payload.get("workspace_id") != self.workspace_id:
            raise Conflict("Invitation token does not match this workspace.")
        if payload.get("email", "").lower() != self.email.lower():
            raise Conflict("Invitation token does not match this email.")

    def _token_payload(self) -> dict[str, Any]:
        try:
            return cast(
                "dict[str, Any]",
                signing.loads(self.token, salt=InvitationFormat().signing_salt, max_age=None),
            )
        except signing.BadSignature as exc:
            raise Conflict("Invitation token is invalid.") from exc

    def _accept_member(self, user: User) -> WorkspaceMember:
        member, _created = WorkspaceMember.objects.select_for_update().get_or_create(
            workspace=self.workspace,
            user=user,
            defaults={"role": self.role, "joined_at": timezone.now()},
        )
        return member

    def _mark_accepted(self) -> None:
        self.accepted_at = timezone.now()
        self.save(update_fields=("accepted_at", "updated_at"))
