from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.http import JsonResponse
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from apps.accounts.models import User
from apps.accounts.schemas.response import (
    UserResponse,
    WorkspaceMembershipResponse,
    WorkspaceResponse,
)
from apps.workspaces.models.member import WorkspaceMember

if TYPE_CHECKING:
    from apps.workspaces.models import Workspace


def json_body(request: Any) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data


def ok(status: int = 200, **extra: Any) -> JsonResponse:
    return JsonResponse({"ok": True, **extra}, status=status)


def err(
    message: str,
    *,
    field: str | None = None,
    status: int = 400,
    **extra: Any,
) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message, "field": field, **extra}, status=status)


def resolve_uid(uidb64: str) -> User | None:
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=uid)
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        return None


def workspace_payload(workspace: Workspace) -> dict[str, str]:
    return WorkspaceResponse(slug=workspace.slug, name=workspace.name).model_dump()


def user_payload(user: User) -> dict[str, Any]:
    return UserResponse(
        id=user.pk,
        email=user.email,
        full_name=user.full_name,
        email_verified=user.is_email_verified,
    ).model_dump()


def user_workspaces(user: User) -> list[dict[str, str]]:
    members = WorkspaceMember.for_user(user)
    return [
        WorkspaceMembershipResponse(
            slug=m.workspace.slug,
            name=m.workspace.name,
            role=m.role,
        ).model_dump()
        for m in members
    ]
