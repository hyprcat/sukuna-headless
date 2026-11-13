from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.api_keys.decorators import requires_scope
from apps.api_keys.principals import ApiKeyPrincipal, SessionPrincipal
from apps.core.decorators import requires_role, workspace_scoped
from apps.core.exceptions import PermissionDenied, ScopeInsufficient


def _info_for(principal: object, *, workspace_pk: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        context=SimpleNamespace(
            principal=principal,
            workspace=SimpleNamespace(pk=workspace_pk),
        )
    )


def _empty_info() -> SimpleNamespace:
    return SimpleNamespace(context=SimpleNamespace(principal=None, workspace=None))


def _api_key_principal(scopes: frozenset[str], *, workspace_id: int = 1) -> ApiKeyPrincipal:
    api_key = SimpleNamespace(workspace_id=workspace_id)
    return ApiKeyPrincipal(api_key=api_key, scopes=scopes)  # type: ignore[arg-type]


def _session_principal(*, can_action: str, workspace_id: int = 1) -> SessionPrincipal:
    member = SimpleNamespace(workspace_id=workspace_id, can=lambda action: action == can_action)
    user = SimpleNamespace()
    return SessionPrincipal(user=user, member=member, role="editor")  # type: ignore[arg-type]


def test_requires_scope_passes_when_scope_present() -> None:
    @requires_scope("runs:write")
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    info = _info_for(_api_key_principal(frozenset({"runs:write"})))
    assert resolver(None, info) == "ok"


def test_requires_scope_rejects_missing_scope() -> None:
    @requires_scope("runs:write")
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    info = _info_for(_api_key_principal(frozenset({"runs:read"})))
    with pytest.raises(ScopeInsufficient):
        resolver(None, info)


def test_requires_scope_rejects_session_principal() -> None:
    @requires_scope("runs:write")
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    info = _info_for(_session_principal(can_action="runs:write"))
    with pytest.raises(PermissionDenied):
        resolver(None, info)


def test_workspace_scoped_passes_when_workspace_matches() -> None:
    @workspace_scoped
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    principal = _api_key_principal(frozenset(), workspace_id=42)
    info = _info_for(principal, workspace_pk=42)
    assert resolver(None, info) == "ok"


def test_workspace_scoped_rejects_cross_workspace() -> None:
    @workspace_scoped
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    principal = _api_key_principal(frozenset(), workspace_id=42)
    info = _info_for(principal, workspace_pk=99)
    with pytest.raises(PermissionDenied):
        resolver(None, info)


def test_requires_role_rejects_api_key_principal() -> None:
    @requires_role("agents:write")
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    info = _info_for(_api_key_principal(frozenset({"runs:write"})))
    with pytest.raises(PermissionDenied):
        resolver(None, info)


def test_requires_role_passes_when_member_can_act() -> None:
    @requires_role("agents:write")
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    info = _info_for(_session_principal(can_action="agents:write"))
    assert resolver(None, info) == "ok"


def test_dual_mode_role_then_scope_accepts_session_or_api_key() -> None:
    @requires_role("runs:write")
    @requires_scope("runs:write")
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    session_info = _info_for(_session_principal(can_action="runs:write"))
    key_info = _info_for(_api_key_principal(frozenset({"runs:write"})))
    assert resolver(None, session_info) == "ok"
    assert resolver(None, key_info) == "ok"


def test_dual_mode_scope_then_role_accepts_session_or_api_key() -> None:
    @requires_scope("runs:write")
    @requires_role("runs:write")
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    session_info = _info_for(_session_principal(can_action="runs:write"))
    key_info = _info_for(_api_key_principal(frozenset({"runs:write"})))
    assert resolver(None, session_info) == "ok"
    assert resolver(None, key_info) == "ok"


def test_workspace_scoped_rejects_missing_context_cleanly() -> None:
    @workspace_scoped
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    with pytest.raises(PermissionDenied):
        resolver(None, _empty_info())


def test_requires_scope_rejects_missing_principal_cleanly() -> None:
    @requires_scope("runs:write")
    def resolver(_root: object, _info: object) -> str:
        return "ok"

    with pytest.raises(PermissionDenied):
        resolver(None, _empty_info())
