from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.exceptions import Conflict, InvalidInput
from apps.workspaces.factories import InvitationFactory, WorkspaceFactory
from apps.workspaces.models import Invitation
from apps.workspaces.models.member import WorkspaceRole

pytestmark = pytest.mark.django_db


def test_create_for_workspace_normalises_email() -> None:
    workspace = WorkspaceFactory()

    invitation = Invitation.create_for_workspace(
        workspace=workspace,
        email="  New.Member@Example.COM  ",
        role=WorkspaceRole.EDITOR,
    )

    assert invitation.email == "new.member@example.com"


def test_create_for_workspace_rejects_invalid_email() -> None:
    workspace = WorkspaceFactory()

    with pytest.raises(InvalidInput) as exc:
        Invitation.create_for_workspace(
            workspace=workspace,
            email="not-an-email",
            role=WorkspaceRole.VIEWER,
        )

    assert exc.value.field == "email"
    assert not Invitation.objects.filter(workspace=workspace).exists()


def test_create_for_workspace_rejects_duplicate_pending_case_insensitive() -> None:
    workspace = WorkspaceFactory()
    InvitationFactory(workspace=workspace, email="member@example.com")

    with pytest.raises(Conflict):
        Invitation.create_for_workspace(
            workspace=workspace,
            email="MEMBER@example.com",
            role=WorkspaceRole.VIEWER,
        )


def test_create_for_workspace_replaces_expired_duplicate() -> None:
    workspace = WorkspaceFactory()
    expired = InvitationFactory(
        workspace=workspace,
        email="member@example.com",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    invitation = Invitation.create_for_workspace(
        workspace=workspace,
        email="member@example.com",
        role=WorkspaceRole.VIEWER,
    )

    assert invitation.pk != expired.pk
    assert not Invitation.objects.filter(pk=expired.pk).exists()


def test_invitation_save_validates_email() -> None:
    workspace = WorkspaceFactory()

    with pytest.raises(ValidationError):
        Invitation.objects.create(
            workspace=workspace,
            email="not-an-email",
            role=WorkspaceRole.VIEWER,
            expires_at=timezone.now() + timedelta(days=7),
        )


def test_revoke_rechecks_stale_instances() -> None:
    invitation = InvitationFactory()
    first = Invitation.objects.get(pk=invitation.pk)
    stale = Invitation.objects.get(pk=invitation.pk)

    first.revoke()

    with pytest.raises(Conflict):
        stale.revoke()
