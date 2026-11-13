from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any, ClassVar, cast

from django.apps import apps
from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.permissions import RolePermissions
from apps.core.events import record_event
from apps.core.exceptions import Conflict
from apps.core.models import TimestampedModel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from apps.accounts.models import User
    from apps.workspaces.models.workspace import Workspace


class WorkspaceRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    EDITOR = "editor", "Editor"
    VIEWER = "viewer", "Viewer"


class WorkspaceMemberQuerySet(models.QuerySet["WorkspaceMember"]):
    def update(self, **kwargs: Any) -> int:
        if _guarded_fields() & set(kwargs):
            raise Conflict("Use workspace membership methods to change members.")
        return super().update(**kwargs)

    def bulk_update(
        self,
        objs: Iterable[WorkspaceMember],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        field_names = set(fields)
        if _guarded_fields() & field_names:
            raise Conflict("Use workspace membership methods to change members.")
        return super().bulk_update(objs, field_names, batch_size=batch_size)

    @transaction.atomic
    def delete(self) -> tuple[int, dict[str, int]]:
        deleted = 0
        totals: dict[str, int] = {}
        locked_members = self.select_for_update().order_by("workspace_id", "pk")
        for member in locked_members.iterator(chunk_size=200):
            count, details = member.delete()
            deleted += count
            totals.update({key: totals.get(key, 0) + value for key, value in details.items()})
        return deleted, totals


class WorkspaceMember(TimestampedModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=16, choices=WorkspaceRole, default=WorkspaceRole.VIEWER)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="workspace_invitations_sent",
    )
    joined_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()
    objects = WorkspaceMemberQuerySet.as_manager()

    class Meta:
        db_table = "workspaces_member"
        ordering = ("workspace_id", "user__email")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("workspace", "user"),
                name="unique_workspace_member",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("workspace", "role")),
            models.Index(fields=("user", "role")),
        ]

    def __str__(self) -> str:
        return f"{self.user} in {self.workspace}"

    @classmethod
    def for_workspace(cls, workspace_id: int) -> models.QuerySet[WorkspaceMember]:
        return cls.objects.select_related("user").filter(workspace_id=workspace_id)

    @classmethod
    def for_user(cls, user: User | int) -> models.QuerySet[WorkspaceMember]:
        if not isinstance(user, int):
            cls.ensure_owner_memberships(user)
        return cls.objects.select_related("workspace").filter(user=user).order_by("workspace__name")

    @classmethod
    def ensure_owner_memberships(cls, user: User) -> None:
        workspaces = cls._owned_workspaces_without_membership(user)
        for workspace in workspaces.iterator(chunk_size=200):
            cls._ensure_owner_membership(workspace, user)

    @classmethod
    def _owned_workspaces_without_membership(cls, user: User) -> models.QuerySet[Workspace]:
        workspace_model = apps.get_model("workspaces", "Workspace")
        return cast(
            "models.QuerySet[Workspace]",
            workspace_model.objects.filter(owner=user).exclude(members__user=user).order_by("pk"),
        )

    @classmethod
    def _ensure_owner_membership(cls, workspace: Workspace, user: User) -> None:
        with suppress(IntegrityError):
            cls.objects.get_or_create(
                workspace=workspace,
                user=user,
                defaults={"role": WorkspaceRole.ADMIN, "joined_at": timezone.now()},
            )

    def can(self, action: str) -> bool:
        return action in RolePermissions().for_role(self.role)

    @property
    def is_admin(self) -> bool:
        return self.role == WorkspaceRole.ADMIN

    @transaction.atomic
    def save(self, *args: Any, **kwargs: Any) -> None:
        self._validate_role()
        owner_id = self._locked_workspace_owner_id()
        if self._demotes_owner(owner_id):
            raise Conflict("Workspace owner must stay an admin.")
        previous_values = self._locked_previous_values()
        self._guard_identity_change(previous_values)
        previous_role = previous_values[2] if previous_values else None
        if self._removes_last_admin(previous_role):
            raise Conflict("A workspace must always have at least one admin.")
        role_changed = self._role_changed(previous_role, kwargs.get("update_fields"))
        super().save(*args, **kwargs)
        if role_changed:
            self._record_role_changed(previous_role)

    def _validate_role(self) -> None:
        if self.role not in WorkspaceRole.values:
            raise Conflict("Workspace role is invalid.")

    def _locked_previous_values(self) -> tuple[int, int, str] | None:
        if self.pk is None:
            return None
        return (
            type(self)
            .objects.select_for_update()
            .values_list("workspace_id", "user_id", "role")
            .get(pk=self.pk)
        )

    def _guard_identity_change(self, previous_values: tuple[int, int, str] | None) -> None:
        if previous_values is None:
            return
        workspace_id, user_id, _role = previous_values
        if self.workspace_id == workspace_id and self.user_id == user_id:
            return
        raise Conflict("Workspace memberships cannot be moved between users or workspaces.")

    def _removes_last_admin(self, previous_role: str | None) -> bool:
        if previous_role != WorkspaceRole.ADMIN or self.role == WorkspaceRole.ADMIN:
            return False
        return not self._other_admins_locked().exists()

    def _role_changed(
        self,
        previous_role: str | None,
        update_fields: Iterable[str] | None,
    ) -> bool:
        if previous_role is None or previous_role == self.role:
            return False
        return update_fields is None or "role" in update_fields

    def _record_role_changed(self, previous_role: str | None) -> None:
        record_event(
            "workspace_member_role_changed",
            distinct_id=str(self.workspace_id),
            properties={
                "member_id": self.pk,
                "user_id": self.user_id,
                "previous_role": previous_role,
                "new_role": self.role,
            },
        )

    def _demotes_owner(self, owner_id: int | None) -> bool:
        return self.user_id == owner_id and self.role != WorkspaceRole.ADMIN

    @transaction.atomic
    def delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        owner_id = self._locked_workspace_owner_id()
        current_role = self._locked_current_role()
        if self.user_id == owner_id:
            raise Conflict("Transfer ownership before removing the owner.")
        self._guard_admin_invariant(current_role)
        return super().delete(using=using, keep_parents=keep_parents)

    def _locked_workspace_owner_id(self) -> int | None:
        if self.workspace_id is None:
            return None
        return (
            self.workspace.__class__.objects.select_for_update()
            .values_list("owner_id", flat=True)
            .get(pk=self.workspace_id)
        )

    def _locked_current_role(self) -> str:
        if self.pk is None:
            return self.role
        return type(self).objects.select_for_update().values_list("role", flat=True).get(pk=self.pk)

    def _guard_admin_invariant(self, role: str) -> None:
        if role != WorkspaceRole.ADMIN:
            return
        if self._other_admins_locked().exists():
            return
        raise Conflict("A workspace must always have at least one admin.")

    def _other_admins_locked(self) -> models.QuerySet[WorkspaceMember]:
        return (
            self.workspace.members.select_for_update()
            .filter(role=WorkspaceRole.ADMIN)
            .exclude(pk=self.pk)
            .order_by("pk")
        )


def _guarded_fields() -> set[str]:
    return {"workspace", "workspace_id", "user", "user_id", "role"}
