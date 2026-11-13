from __future__ import annotations

import pytest

from apps.api_keys.factories import create_with_secret
from apps.api_keys.principals import ApiKeyPrincipal, SessionPrincipal
from apps.workspaces.factories import (
    UserFactory,
    WorkspaceFactory,
    WorkspaceMemberFactory,
)
from apps.workspaces.models.member import WorkspaceRole

pytestmark = pytest.mark.django_db


def test_session_principal_exposes_workspace_id_and_empty_scopes() -> None:
    workspace = WorkspaceFactory()
    user = UserFactory()
    member = WorkspaceMemberFactory(workspace=workspace, user=user, role=WorkspaceRole.EDITOR)

    principal = SessionPrincipal(user=user, member=member, role=member.role)

    assert principal.workspace_id == workspace.pk
    assert principal.scopes == frozenset()
    assert principal.member is member


def test_api_key_principal_exposes_workspace_id_and_no_member() -> None:
    api_key, _ = create_with_secret(scopes=("runs:read", "runs:write"))

    principal = ApiKeyPrincipal(
        api_key=api_key,
        scopes=frozenset(api_key.scopes),
    )

    assert principal.workspace_id == api_key.workspace_id
    assert principal.member is None
    assert "runs:read" in principal.scopes
