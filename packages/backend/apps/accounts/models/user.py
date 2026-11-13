from __future__ import annotations

from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.accounts.models.managers import UserManager
from apps.core.models import TimestampedModel


class User(AbstractBaseUser, PermissionsMixin, TimestampedModel):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True, default="")
    email_verified_at = models.DateTimeField(null=True, blank=True, default=None)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        db_table = "accounts_user"
        ordering = ("-created_at",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("is_active", "-created_at")),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def short_name(self) -> str:
        if self.full_name:
            return self.full_name.split(" ", 1)[0]
        return self.email.split("@", 1)[0]

    def get_full_name(self) -> str:
        return self.full_name or self.email

    def get_short_name(self) -> str:
        return self.short_name

    def can_be_edited_by(self, actor: User) -> bool:
        return actor.pk == self.pk or actor.is_superuser

    def can_be_viewed_by(self, actor: User) -> bool:
        return actor.is_active and (actor.pk == self.pk or actor.is_staff)

    def deactivate(self) -> None:
        self.is_active = False
        self.save(update_fields=("is_active", "updated_at"))

    def reactivate(self) -> None:
        self.is_active = True
        self.save(update_fields=("is_active", "updated_at"))

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    def verify_email(self) -> None:
        if self.email_verified_at is not None:
            return
        self.email_verified_at = timezone.now()
        self.save(update_fields=("email_verified_at", "updated_at"))
