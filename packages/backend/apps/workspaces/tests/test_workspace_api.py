from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.agents.factories import AgentFactory
from apps.api_keys.principals import ApiKeyPrincipal
from apps.billing.factories import CreditWalletFactory
from apps.end_users.factories import EndUserFactory
from apps.insights.factories import InsightFactory
from apps.knowledge.factories import KnowledgeFactory
from apps.runs.factories import RunFactory
from apps.tools.factories import ToolFactory
from apps.workspaces.api.queries import WorkspaceQuery
from apps.workspaces.factories import WorkspaceFactory, WorkspaceMemberFactory
from apps.workspaces.models.member import WorkspaceRole

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q(WorkspaceQuery):
    pass


_schema = strawberry.Schema(query=_Q, extensions=[DjangoOptimizerExtension])


def _ws_ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(
        workspace_id=workspace.pk,  # type: ignore[union-attr]
        can=lambda _action: True,
    )
    principal = SimpleNamespace(
        workspace_id=workspace.pk,  # type: ignore[union-attr]
        member=member,
        scopes=frozenset(),
    )
    return SimpleNamespace(workspace=workspace, principal=principal)


def _api_key_ctx(workspace: object) -> SimpleNamespace:
    api_key = SimpleNamespace(workspace_id=workspace.pk)  # type: ignore[union-attr]
    principal = ApiKeyPrincipal(
        api_key=api_key,  # type: ignore[arg-type]
        scopes=frozenset({"workspace:read"}),
    )
    return SimpleNamespace(workspace=workspace, principal=principal)


WORKSPACE_AGENTS_QUERY = """
query {
    workspace {
        name
        agents { totalCount edges { node { name } } }
    }
}
"""


def test_workspace_agents_connection() -> None:
    ws = WorkspaceFactory()
    AgentFactory(workspace=ws, name="Agent A")
    AgentFactory(workspace=ws, name="Agent B")
    result = _schema.execute_sync(WORKSPACE_AGENTS_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    agents = result.data["workspace"]["agents"]
    assert agents["totalCount"] == 2
    names = {e["node"]["name"] for e in agents["edges"]}
    assert names == {"Agent A", "Agent B"}


WORKSPACE_BY_ID_QUERY = """
query($id: ID!) {
    workspace(id: $id) { name }
}
"""


def test_workspace_accepts_matching_id_argument() -> None:
    ws = WorkspaceFactory()
    result = _schema.execute_sync(
        WORKSPACE_BY_ID_QUERY,
        variable_values={"id": str(ws.pk)},
        context_value=_ws_ctx(ws),
    )
    assert result.errors is None
    assert result.data["workspace"]["name"] == ws.name


def test_workspace_id_argument_cannot_select_another_workspace() -> None:
    ws = WorkspaceFactory()
    other = WorkspaceFactory()
    result = _schema.execute_sync(
        WORKSPACE_BY_ID_QUERY,
        variable_values={"id": str(other.pk)},
        context_value=_ws_ctx(ws),
    )
    assert result.errors is None
    assert result.data["workspace"] is None


def test_workspace_query_rejects_api_key_principal() -> None:
    ws = WorkspaceFactory()
    result = _schema.execute_sync(WORKSPACE_AGENTS_QUERY, context_value=_api_key_ctx(ws))
    assert result.errors is not None
    assert "not permitted" in result.errors[0].message


WORKSPACE_TOOLS_QUERY = """
query {
    workspace {
        tools { totalCount edges { node { name } } }
    }
}
"""


def test_workspace_tools_connection() -> None:
    ws = WorkspaceFactory()
    ToolFactory(workspace=ws, name="tool-a")
    ToolFactory(workspace=ws, name="tool-b")
    ToolFactory(workspace=ws, name="tool-c")
    result = _schema.execute_sync(WORKSPACE_TOOLS_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    tools = result.data["workspace"]["tools"]
    assert tools["totalCount"] == 3


WORKSPACE_MEMBERS_QUERY = """
query {
    workspace {
        members { totalCount edges { node { role userEmail } } }
    }
}
"""


def test_workspace_members_connection() -> None:
    ws = WorkspaceFactory()
    WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.ADMIN)
    WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.VIEWER)
    result = _schema.execute_sync(WORKSPACE_MEMBERS_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    members = result.data["workspace"]["members"]
    assert members["totalCount"] >= 2
    roles = {e["node"]["role"] for e in members["edges"]}
    assert "admin" in roles
    assert "viewer" in roles


WORKSPACE_WALLET_QUERY = """
query {
    workspace {
        wallet { balanceUsd available }
    }
}
"""


def test_workspace_wallet_present() -> None:
    ws = WorkspaceFactory()
    CreditWalletFactory(workspace=ws, balance_usd="50.00")
    result = _schema.execute_sync(WORKSPACE_WALLET_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    wallet = result.data["workspace"]["wallet"]
    assert wallet is not None
    assert float(wallet["balanceUsd"]) == 50.0


def test_workspace_wallet_null_when_absent() -> None:
    ws = WorkspaceFactory()
    result = _schema.execute_sync(WORKSPACE_WALLET_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    assert result.data["workspace"]["wallet"] is None


WORKSPACE_KNOWLEDGE_QUERY = """
query {
    workspace {
        knowledgeBases { totalCount }
    }
}
"""


def test_workspace_knowledge_connection() -> None:
    ws = WorkspaceFactory()
    KnowledgeFactory(workspace=ws)
    KnowledgeFactory(workspace=ws)
    result = _schema.execute_sync(WORKSPACE_KNOWLEDGE_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    assert result.data["workspace"]["knowledgeBases"]["totalCount"] == 2


WORKSPACE_END_USERS_QUERY = """
query {
    workspace {
        endUsers { totalCount }
    }
}
"""


def test_workspace_end_users_connection() -> None:
    ws = WorkspaceFactory()
    EndUserFactory(workspace=ws)
    result = _schema.execute_sync(WORKSPACE_END_USERS_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    assert result.data["workspace"]["endUsers"]["totalCount"] == 1


WORKSPACE_RUNS_QUERY = """
query {
    workspace {
        runs { totalCount }
    }
}
"""


def test_workspace_runs_connection() -> None:
    ws = WorkspaceFactory()
    RunFactory(workspace=ws)
    RunFactory(workspace=ws)
    result = _schema.execute_sync(WORKSPACE_RUNS_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    assert result.data["workspace"]["runs"]["totalCount"] == 2


WORKSPACE_RUNS_FILTER_QUERY = """
query($status: String) {
    workspace {
        runs(status: $status) { totalCount }
    }
}
"""


def test_workspace_runs_connection_accepts_status_filter() -> None:
    ws = WorkspaceFactory()
    RunFactory(workspace=ws)
    RunFactory(workspace=ws, finished=True)
    result = _schema.execute_sync(
        WORKSPACE_RUNS_FILTER_QUERY,
        variable_values={"status": "finished"},
        context_value=_ws_ctx(ws),
    )
    assert result.errors is None
    assert result.data["workspace"]["runs"]["totalCount"] == 1


WORKSPACE_LEDGER_QUERY = """
query {
    workspace {
        wallet {
            ledger { totalCount edges { node { kind deltaUsd } } }
        }
    }
}
"""


def test_workspace_wallet_exposes_ledger_connection() -> None:
    ws = WorkspaceFactory()
    wallet = CreditWalletFactory(workspace=ws)
    wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="pay_1")
    wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="pay_2")
    result = _schema.execute_sync(WORKSPACE_LEDGER_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    ledger = result.data["workspace"]["wallet"]["ledger"]
    assert ledger["totalCount"] == 2


WORKSPACE_INSIGHTS_QUERY = """
query {
    workspace {
        insights { totalCount }
    }
}
"""


def test_workspace_insights_connection() -> None:
    ws = WorkspaceFactory()
    InsightFactory(workspace=ws)
    result = _schema.execute_sync(WORKSPACE_INSIGHTS_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    assert result.data["workspace"]["insights"]["totalCount"] == 1


WORKSPACE_OWNER_QUERY = """
query {
    workspace {
        ownerEmail ownerId
    }
}
"""


def test_workspace_owner_fields() -> None:
    ws = WorkspaceFactory()
    result = _schema.execute_sync(WORKSPACE_OWNER_QUERY, context_value=_ws_ctx(ws))
    assert result.errors is None
    data = result.data["workspace"]
    assert data["ownerEmail"] == ws.owner.email
    assert data["ownerId"] == str(ws.owner_id)
