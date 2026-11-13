from __future__ import annotations

import re
import secrets

from django.db import IntegrityError, transaction
from pydantic import BaseModel, ConfigDict

from apps.accounts.models import User
from apps.accounts.tokens import check_email_verification_token
from apps.core.events import record_event
from apps.core.exceptions import Conflict
from apps.workspaces.models import Workspace
from apps.workspaces.models.member import WorkspaceMember


class OnboardingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug_token_bytes: int = 3
    max_slug_attempts: int = 8


def first_workspace(user: User) -> Workspace | None:
    member = WorkspaceMember.objects.filter(user=user).select_related("workspace").first()
    return member.workspace if member else None


def ensure_personal_workspace(user: User) -> Workspace:
    workspace = first_workspace(user)
    return workspace if workspace else _make_personal_workspace(user)


def verify_email_and_workspace(user: User, token: str) -> tuple[User, Workspace, bool] | None:
    if not _can_use_verification_token(user, token):
        return None
    with transaction.atomic():
        return _verify_locked_email(user, token)


def _can_use_verification_token(user: User, token: str) -> bool:
    return user.is_active and check_email_verification_token(user, token)


def _verify_locked_email(user: User, token: str) -> tuple[User, Workspace, bool] | None:
    locked = User.objects.select_for_update().get(pk=user.pk)
    if not locked.is_active:
        return None
    if locked.is_email_verified:
        return _verification_result(locked, already_verified=True)
    if not _can_use_verification_token(locked, token):
        return None
    locked.verify_email()
    _record_email_verified(locked)
    return _verification_result(locked, already_verified=False)


def _verification_result(user: User, *, already_verified: bool) -> tuple[User, Workspace, bool]:
    return user, ensure_personal_workspace(user), already_verified


def _record_email_verified(user: User) -> None:
    record_event(
        "email_verified",
        distinct_id=str(user.pk),
        properties={"email": user.email},
    )


def _make_personal_workspace(user: User) -> Workspace:
    base = _slug_base(user)
    config = OnboardingConfig()
    for attempt in range(config.max_slug_attempts):
        slug = _candidate_slug(base, attempt, config)
        workspace = _try_create_workspace(user, slug)
        if workspace is not None:
            return workspace
    raise Conflict("Could not create a workspace slug. Try again.")


def _slug_base(user: User) -> str:
    return re.sub(r"[^a-z0-9]+", "-", user.email.split("@")[0].lower()).strip("-") or "workspace"


def _candidate_slug(base: str, attempt: int, config: OnboardingConfig) -> str:
    if attempt == 0:
        return base
    return f"{base}-{secrets.token_hex(config.slug_token_bytes)}"


def _try_create_workspace(user: User, slug: str) -> Workspace | None:
    try:
        with transaction.atomic():
            return Workspace.objects.create(
                name=f"{user.short_name}'s workspace",
                slug=slug,
                owner=user,
            )
    except IntegrityError:
        return None
