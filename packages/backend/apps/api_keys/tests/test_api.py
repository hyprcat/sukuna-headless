from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import strawberry
from strawberry import relay

from apps.api_keys.api.mutations import APIKeyMutation
from apps.api_keys.models import APIKey
from apps.api_keys.principals import SessionPrincipal
from apps.workspaces.factories import WorkspaceFactory, WorkspaceMemberFactory
from apps.workspaces.models.member import WorkspaceRole

if TYPE_CHECKING:
    from apps.workspaces.models import Workspace, WorkspaceMember

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q:
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class _M(APIKeyMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M)


CREATE_MUTATION = """
mutation Create($input: CreateAPIKeyInput!) {
    createApiKey(input: $input) {
        success
        errors { code message field }
        plaintextSecret
        apiKey { name keyPrefix maskedValue scopes isActive createdByEmail }
    }
}
"""


REVOKE_MUTATION = """
mutation Revoke($input: RevokeAPIKeyInput!) {
    revokeApiKey(input: $input) {
        success
        errors { code message field }
        apiKey { keyPrefix isActive revokedAt }
    }
}
"""


def _session_ctx(member: WorkspaceMember, *, workspace: Workspace | None = None) -> SimpleNamespace:
    principal = SessionPrincipal(user=member.user, member=member, role=member.role)
    return SimpleNamespace(workspace=workspace or member.workspace, principal=principal)


def _api_key_ctx(api_key: APIKey) -> SimpleNamespace:
    principal = SimpleNamespace(
        workspace_id=api_key.workspace_id,
        member=None,
        scopes=frozenset(api_key.scopes),
    )
    return SimpleNamespace(workspace=api_key.workspace, principal=principal)


def _admin_member() -> WorkspaceMember:
    return WorkspaceMemberFactory(role=WorkspaceRole.ADMIN)


def _gid(type_name: str, pk: object) -> str:
    return relay.to_base64(type_name, pk)


def test_create_api_key_via_admin_session_returns_secret_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr("apps.api_keys.models.api_key.record_event", _capture(events))
    member = _admin_member()

    result = _schema.execute_sync(
        CREATE_MUTATION,
        variable_values={"input": {"name": "Dashboard key", "scopes": ["runs:read"]}},
        context_value=_session_ctx(member),
    )

    assert result.errors is None
    data = result.data["createApiKey"]
    api_key = APIKey.objects.get(name="Dashboard key")
    assert data["success"] is True
    assert data["plaintextSecret"].startswith("ms_")
    assert data["apiKey"]["keyPrefix"] in data["plaintextSecret"]
    assert data["apiKey"]["maskedValue"].endswith(f"{data['apiKey']['keyPrefix']}...")
    assert data["apiKey"]["maskedValue"] != data["plaintextSecret"]
    assert api_key.verify(data["plaintextSecret"])
    assert api_key.created_by_id == member.user_id
    assert events[0][0] == "api_key_created"


def test_create_api_key_rejects_api_key_principal() -> None:
    api_key, _secret = APIKey.create_for_workspace(
        WorkspaceFactory(),
        name="Existing",
        scopes=["runs:read"],
    )

    result = _schema.execute_sync(
        CREATE_MUTATION,
        variable_values={"input": {"name": "Blocked", "scopes": ["runs:read"]}},
        context_value=_api_key_ctx(api_key),
    )

    assert result.errors is not None
    assert "not permitted" in result.errors[0].message
    assert not APIKey.objects.filter(name="Blocked").exists()


def test_create_api_key_invalid_scope_returns_mutation_error() -> None:
    member = _admin_member()

    result = _schema.execute_sync(
        CREATE_MUTATION,
        variable_values={"input": {"name": "Bad scope", "scopes": ["bad:scope"]}},
        context_value=_session_ctx(member),
    )

    data = result.data["createApiKey"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "scopes"
    assert not APIKey.objects.filter(name="Bad scope").exists()


def test_create_api_key_blank_name_returns_mutation_error() -> None:
    member = _admin_member()

    result = _schema.execute_sync(
        CREATE_MUTATION,
        variable_values={"input": {"name": "", "scopes": ["runs:read"]}},
        context_value=_session_ctx(member),
    )

    data = result.data["createApiKey"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "name"


def test_revoke_api_key_schema_uses_input_contract() -> None:
    sdl = str(_schema)

    assert "revokeApiKey(input:" in sdl
    assert "revokeApiKey(id:" not in sdl
    assert "input RevokeAPIKeyInput" in sdl


def test_revoke_api_key_via_admin_session_records_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr("apps.api_keys.models.api_key.record_event", _capture(events))
    member = _admin_member()
    api_key, _secret = APIKey.create_for_workspace(
        member.workspace,
        name="Retired",
        scopes=["runs:read"],
        created_by=member.user,
    )

    result = _schema.execute_sync(
        REVOKE_MUTATION,
        variable_values={"input": {"id": _gid("APIKeyType", api_key.pk), "reason": "rotation"}},
        context_value=_session_ctx(member),
    )

    api_key.refresh_from_db()
    data = result.data["revokeApiKey"]
    assert result.errors is None
    assert data["success"] is True
    assert data["apiKey"]["isActive"] is False
    assert api_key.revoked_at is not None
    assert events[-1][0] == "api_key_revoked"


def test_revoke_api_key_rejects_wrong_relay_id_type_as_payload_error() -> None:
    member = _admin_member()

    result = _schema.execute_sync(
        REVOKE_MUTATION,
        variable_values={"input": {"id": _gid("WorkspaceType", member.workspace.pk)}},
        context_value=_session_ctx(member),
    )

    data = result.data["revokeApiKey"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "id"


def test_revoke_api_key_cross_workspace_returns_not_found() -> None:
    owner = _admin_member()
    other = _admin_member()
    api_key, _secret = APIKey.create_for_workspace(
        owner.workspace,
        name="Private",
        scopes=["runs:read"],
    )

    result = _schema.execute_sync(
        REVOKE_MUTATION,
        variable_values={"input": {"id": str(api_key.pk), "reason": "rotation"}},
        context_value=_session_ctx(other),
    )

    data = result.data["revokeApiKey"]
    assert result.errors is None
    assert data["success"] is False
    assert data["errors"][0]["code"] == "NOT_FOUND"


def test_create_api_key_rejects_editor_session() -> None:
    member = WorkspaceMemberFactory(role=WorkspaceRole.EDITOR)

    result = _schema.execute_sync(
        CREATE_MUTATION,
        variable_values={"input": {"name": "Blocked", "scopes": ["runs:read"]}},
        context_value=_session_ctx(member),
    )

    assert result.errors is not None
    assert "not permitted" in result.errors[0].message
    assert not APIKey.objects.filter(name="Blocked").exists()


def _capture(
    events: list[tuple[str, dict[str, object]]],
) -> object:
    def fake_record_event(name: str, **kwargs: object) -> None:
        events.append((name, kwargs))

    return fake_record_event
