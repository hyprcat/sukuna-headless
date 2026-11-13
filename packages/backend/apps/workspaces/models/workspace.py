from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify
from pydantic import BaseModel, ConfigDict
from simple_history.models import HistoricalRecords

from apps.core.events import record_event
from apps.core.exceptions import Conflict, InvalidInput, NotFound
from apps.core.models import TimestampedModel
from apps.workspaces.models.member import WorkspaceMember, WorkspaceRole


class WorkspaceFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_slug_suffix_attempts: int = 100
    slug_max_base_length: int = 60


if TYPE_CHECKING:
    from collections.abc import Iterable

    from apps.accounts.models import User


class WorkspaceQuerySet(models.QuerySet["Workspace"]):
    def update(self, **kwargs: Any) -> int:
        if {"owner", "owner_id"} & set(kwargs):
            raise Conflict("Use transfer_ownership() to change workspace owner.")
        return super().update(**kwargs)


class Workspace(TimestampedModel):
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=80, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_workspaces",
    )
    billing_email = models.EmailField(blank=True, default="")
    dodo_customer_id = models.CharField(max_length=128, blank=True, null=True, unique=True)
    suspended_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()
    objects = WorkspaceQuerySet.as_manager()

    class Meta:
        db_table = "workspaces_workspace"
        ordering = ("name",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("owner", "suspended_at")),
        ]

    def __str__(self) -> str:
        return self.name

    @transaction.atomic
    def save(self, *args: Any, **kwargs: Any) -> None:
        previous_owner_id = self._previous_owner_id()
        owner_update_requested = self._owner_update_requested(kwargs.get("update_fields"))
        super().save(*args, **kwargs)
        if owner_update_requested and previous_owner_id != self.owner_id:
            self.add_member(self.owner, WorkspaceRole.ADMIN)

    def _previous_owner_id(self) -> int | None:
        if self.pk is None:
            return None
        return type(self).objects.filter(pk=self.pk).values_list("owner_id", flat=True).first()

    def _owner_update_requested(self, update_fields: Iterable[str] | None) -> bool:
        if update_fields is None:
            return True
        return "owner" in update_fields or "owner_id" in update_fields

    @transaction.atomic
    def add_member(self, user: User, role: str) -> WorkspaceMember:
        self._validate_role(role)
        member = self.members.select_for_update().order_by("pk").filter(user=user).first()
        if member is None:
            return WorkspaceMember.objects.create(
                workspace=self, user=user, role=role, joined_at=timezone.now()
            )
        member.role = role
        member.joined_at = member.joined_at or timezone.now()
        member.save(update_fields=("role", "joined_at", "updated_at"))
        return member

    @transaction.atomic
    def remove_member(self, member: WorkspaceMember) -> None:
        if member.workspace_id != self.pk:
            raise Conflict("Member does not belong to this workspace.")
        if member.user_id == self.owner_id:
            raise Conflict("Transfer ownership before removing the owner.")
        self._guard_admin_removal(member)
        user_id = member.user_id
        member.delete()
        record_event(
            "workspace_member_removed",
            distinct_id=str(self.pk),
            properties={"user_id": user_id, "workspace_id": self.pk},
        )

    @transaction.atomic
    def transfer_ownership(self, new_owner: User) -> None:
        locked = self._locked_self()
        previous_owner_id = locked.owner_id
        locked.owner = new_owner
        locked.save(update_fields=("owner", "updated_at"))
        self._sync_locked_owner(locked, new_owner)
        self._record_ownership_transferred(previous_owner_id, new_owner.pk)

    @transaction.atomic
    def transfer_ownership_to_user_id(self, user_id: int | str) -> None:
        new_owner = self._user_by_id_or_raise(user_id)
        locked = self._locked_self()
        if not locked.members.filter(user=new_owner).exists():
            raise InvalidInput("New owner must be a workspace member.", field="user_id")
        locked.transfer_ownership(new_owner)
        self._sync_locked_owner(locked, new_owner)

    def _locked_self(self) -> Workspace:
        if self.pk is None:
            raise Conflict("Workspace must be saved before ownership transfer.")
        try:
            return type(self).objects.select_for_update().get(pk=self.pk)
        except type(self).DoesNotExist:
            raise NotFound("Workspace not found.") from None

    def _sync_locked_owner(self, locked: Workspace, new_owner: User) -> None:
        self.owner = new_owner
        self.owner_id = locked.owner_id
        self.updated_at = locked.updated_at

    def _record_ownership_transferred(self, previous_owner_id: int, new_owner_id: int) -> None:
        record_event(
            "workspace_ownership_transferred",
            distinct_id=str(self.pk),
            properties={
                "previous_owner_id": previous_owner_id,
                "new_owner_id": new_owner_id,
            },
        )

    def remove_member_by_id(self, member_id: int | str) -> None:
        self.remove_member(self.get_member_or_raise(member_id))

    def get_member_or_raise(self, member_id: int | str) -> WorkspaceMember:
        try:
            return self.members.get(pk=member_id)
        except (WorkspaceMember.DoesNotExist, ValueError):
            raise NotFound("Member not found.") from None

    @transaction.atomic
    def change_member_role(self, member_id: int | str, role: str) -> WorkspaceMember:
        if role not in WorkspaceRole.values:
            raise InvalidInput("Invalid role.", field="role")
        member = self.get_member_or_raise(member_id)
        member.role = role
        member.save(update_fields=("role", "updated_at"))
        return member

    @classmethod
    def get_with_owner(cls, pk: int) -> Workspace:
        # Annotate member_count so WorkspaceType's annotated field resolves
        # on this hand-fetched instance (custom resolvers bypass strawberry-django's annotation).
        return (
            cls.objects.select_related("owner")
            .annotate(member_count=models.Count("members"))
            .get(pk=pk)
        )

    @classmethod
    @transaction.atomic
    def create_for_user(
        cls,
        *,
        user: User,
        name: str,
        slug: str = "",
        billing_email: str = "",
    ) -> Workspace:
        resolved_slug = cls._resolved_slug(name=name, slug=slug)
        workspace = cls._create_record(user, name, resolved_slug, billing_email)
        cls._record_created(user, workspace)
        return workspace

    @classmethod
    def _resolved_slug(cls, *, name: str, slug: str) -> str:
        if not name.strip():
            raise InvalidInput("Workspace name is required.", field="name")
        resolved_slug = slug.strip() or cls._generate_slug(name)
        if not resolved_slug:
            raise InvalidInput("Could not generate a valid slug.", field="slug")
        return resolved_slug

    @classmethod
    def _create_record(
        cls,
        user: User,
        name: str,
        slug: str,
        billing_email: str,
    ) -> Workspace:
        cls._validate_billing_email(billing_email)
        workspace = cls(name=name.strip(), slug=slug, owner=user, billing_email=billing_email)
        workspace.save()
        return workspace

    @staticmethod
    def _record_created(user: User, workspace: Workspace) -> None:
        record_event(
            "workspace_created",
            distinct_id=str(user.pk),
            properties={"workspace_id": workspace.pk, "slug": workspace.slug},
        )

    @classmethod
    def _generate_slug(cls, name: str) -> str:
        fmt = WorkspaceFormat()
        base = slugify(name)[: fmt.slug_max_base_length]
        if not base:
            return ""
        candidate = base
        suffix = 1
        while cls.objects.filter(slug=candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
            if suffix > fmt.max_slug_suffix_attempts:
                return ""
        return candidate

    def update_settings(self, *, name: str | None = None, billing_email: str | None = None) -> None:
        fields: list[str] = ["updated_at"]
        email_changed = False
        if name is not None:
            if not name.strip():
                raise InvalidInput("Workspace name is required.", field="name")
            self.name = name.strip()
            fields.append("name")
        if billing_email is not None:
            self._validate_billing_email(billing_email)
            email_changed = billing_email != self.billing_email
            self.billing_email = billing_email
            fields.append("billing_email")
        self.save(update_fields=fields)
        if email_changed and self.dodo_customer_id:
            from apps.billing.tasks.reconcile import sync_dodo_customer_email  # noqa: PLC0415

            sync_dodo_customer_email.enqueue(self.pk)

    def suspend(self) -> None:
        if self.suspended_at is None:
            self.suspended_at = timezone.now()
            self.save(update_fields=("suspended_at", "updated_at"))

    def _validate_role(self, role: str) -> None:
        if role not in WorkspaceRole.values:
            raise Conflict("Workspace role is invalid.")

    @staticmethod
    def _validate_billing_email(email: str) -> None:
        if not email:
            return
        try:
            validate_email(email)
        except ValidationError:
            raise InvalidInput("Enter a valid billing email.", field="billing_email") from None

    @staticmethod
    def _user_by_id_or_raise(user_id: int | str) -> User:
        user_model = apps.get_model("accounts", "User")
        try:
            return cast("User", user_model.objects.get(pk=user_id))
        except (user_model.DoesNotExist, ValueError):
            raise NotFound("User not found.") from None

    def _guard_admin_removal(self, member: WorkspaceMember) -> None:
        if member.role != WorkspaceRole.ADMIN:
            return
        if self.members.filter(role=WorkspaceRole.ADMIN).exclude(pk=member.pk).exists():
            return
        raise Conflict("A workspace must always have at least one admin.")
