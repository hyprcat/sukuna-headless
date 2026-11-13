from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import BaseUserManager
from django.db import models

if TYPE_CHECKING:
    from apps.accounts.models.user import User


class UserQuerySet(models.QuerySet["User"]):
    def active(self) -> UserQuerySet:
        return self.filter(is_active=True)

    def staff(self) -> UserQuerySet:
        return self.filter(is_staff=True)


class UserManager(BaseUserManager["User"]):
    def get_queryset(self) -> UserQuerySet:
        return UserQuerySet(self.model, using=self._db)

    def active(self) -> UserQuerySet:
        return self.get_queryset().active()

    def staff(self) -> UserQuerySet:
        return self.get_queryset().staff()

    def _build(self, email: str, password: str | None, **extra: Any) -> User:
        if not email:
            raise ValueError("Users must have an email address.")
        user: User = self.model(email=self.normalize_email(email), **extra)
        user.password = make_password(password) if password else make_password(None)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        user = self._build(email, password, **extra)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra["is_staff"] is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra["is_superuser"] is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra)
