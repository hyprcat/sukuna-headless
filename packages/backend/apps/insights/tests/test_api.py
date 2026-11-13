from __future__ import annotations

from types import SimpleNamespace

import pytest
import strawberry
from strawberry import relay

from apps.insights.api.mutations import InsightMutation
from apps.insights.api.queries import InsightQuery
from apps.insights.factories import InsightFactory
from apps.insights.models import InsightCategory, InsightStatus
from apps.workspaces.factories import UserFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q(InsightQuery):
    pass


@strawberry.type
class _M(InsightMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M)


def _session_ctx(*, workspace_pk: int, allowed: set[str], user_id: int = 1) -> SimpleNamespace:
    ws = SimpleNamespace(pk=workspace_pk)
    member = SimpleNamespace(
        workspace_id=workspace_pk,
        user_id=user_id,
        can=lambda action: action in allowed,
    )
    principal = SimpleNamespace(workspace_id=workspace_pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=ws, principal=principal)


def _api_ctx(*, workspace_pk: int) -> SimpleNamespace:
    ws = SimpleNamespace(pk=workspace_pk)
    principal = SimpleNamespace(
        workspace_id=workspace_pk,
        member=None,
        scopes=frozenset({"runs:read"}),
    )
    return SimpleNamespace(workspace=ws, principal=principal)


def _gid(type_name: str, pk: object) -> str:
    return relay.to_base64(type_name, pk)


INSIGHTS_QUERY = """
query Insights($status: String) {
    insights(status: $status) {
        edges { node { title status } }
    }
}
"""


def test_insights_query_defaults_to_visible_insights() -> None:
    active = InsightFactory(title="Active")
    InsightFactory(workspace=active.workspace, title="Pinned", pinned=True)
    InsightFactory(workspace=active.workspace, title="Dismissed", dismissed=True)
    ctx = _session_ctx(workspace_pk=active.workspace_id, allowed={"insights:read"})

    result = _schema.execute_sync(INSIGHTS_QUERY, context_value=ctx)

    assert result.errors is None
    titles = [edge["node"]["title"] for edge in result.data["insights"]["edges"]]
    assert titles == ["Pinned", "Active"]


def test_insights_query_can_filter_dismissed_status() -> None:
    dismissed = InsightFactory(title="Dismissed", dismissed=True)
    InsightFactory(workspace=dismissed.workspace, title="Active")
    ctx = _session_ctx(workspace_pk=dismissed.workspace_id, allowed={"insights:read"})

    result = _schema.execute_sync(
        INSIGHTS_QUERY,
        variable_values={"status": InsightStatus.DISMISSED},
        context_value=ctx,
    )

    assert result.errors is None
    edges = result.data["insights"]["edges"]
    assert [edge["node"]["title"] for edge in edges] == ["Dismissed"]


SUMMARY_QUERY = """
query Summary {
    insightSummary {
        totalActive
        totalPinned
        byCategory { category count }
    }
}
"""


def test_insight_summary_returns_visible_category_distribution() -> None:
    insight = InsightFactory(category=InsightCategory.QUALITY_ISSUE)
    InsightFactory(workspace=insight.workspace, category=InsightCategory.QUALITY_ISSUE, pinned=True)
    InsightFactory(
        workspace=insight.workspace,
        category=InsightCategory.CAPABILITY_GAP,
        dismissed=True,
    )
    ctx = _session_ctx(workspace_pk=insight.workspace_id, allowed={"insights:read"})

    result = _schema.execute_sync(SUMMARY_QUERY, context_value=ctx)

    assert result.errors is None
    summary = result.data["insightSummary"]
    assert summary["totalActive"] == 1
    assert summary["totalPinned"] == 1
    assert summary["byCategory"] == [{"category": "quality_issue", "count": 2}]


def test_insight_query_rejects_api_key_principal() -> None:
    insight = InsightFactory()
    ctx = _api_ctx(workspace_pk=insight.workspace_id)

    result = _schema.execute_sync(SUMMARY_QUERY, context_value=ctx)

    assert result.errors is not None
    assert "not permitted" in result.errors[0].message


DISMISS_MUTATION = """
mutation Dismiss($id: ID!) {
    dismissInsight(id: $id) {
        success
        errors { code message field }
        insight { status }
    }
}
"""


def test_dismiss_insight_mutation_maps_conflicts() -> None:
    insight = InsightFactory(dismissed=True)
    ctx = _session_ctx(workspace_pk=insight.workspace_id, allowed={"insights:dismiss"})

    result = _schema.execute_sync(
        DISMISS_MUTATION,
        variable_values={"id": str(insight.pk)},
        context_value=ctx,
    )

    assert result.errors is None
    data = result.data["dismissInsight"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


PIN_MUTATION = """
mutation Pin($id: ID!) {
    pinInsight(id: $id) {
        success
        errors { code message field }
        insight { status }
    }
}
"""


UNPIN_MUTATION = """
mutation Unpin($id: ID!) {
    unpinInsight(id: $id) {
        success
        errors { code message field }
        insight { status }
    }
}
"""


def test_insight_lifecycle_mutations_accept_relay_global_ids() -> None:
    insight = InsightFactory()
    user = UserFactory()
    ctx = _session_ctx(
        workspace_pk=insight.workspace_id,
        allowed={"insights:dismiss", "insights:pin"},
        user_id=user.pk,
    )

    pinned = _schema.execute_sync(
        PIN_MUTATION,
        variable_values={"id": _gid("InsightType", insight.pk)},
        context_value=ctx,
    )
    assert pinned.errors is None
    assert pinned.data["pinInsight"]["success"] is True
    assert pinned.data["pinInsight"]["insight"]["status"] == InsightStatus.PINNED

    unpinned = _schema.execute_sync(
        UNPIN_MUTATION,
        variable_values={"id": _gid("InsightType", insight.pk)},
        context_value=ctx,
    )
    assert unpinned.errors is None
    assert unpinned.data["unpinInsight"]["success"] is True
    assert unpinned.data["unpinInsight"]["insight"]["status"] == InsightStatus.ACTIVE

    dismissed = _schema.execute_sync(
        DISMISS_MUTATION,
        variable_values={"id": _gid("InsightType", insight.pk)},
        context_value=ctx,
    )
    assert dismissed.errors is None
    assert dismissed.data["dismissInsight"]["success"] is True
    assert dismissed.data["dismissInsight"]["insight"]["status"] == InsightStatus.DISMISSED


def test_dismiss_insight_rejects_wrong_relay_id_type() -> None:
    insight = InsightFactory()
    ctx = _session_ctx(workspace_pk=insight.workspace_id, allowed={"insights:dismiss"})

    result = _schema.execute_sync(
        DISMISS_MUTATION,
        variable_values={"id": _gid("ToolType", insight.pk)},
        context_value=ctx,
    )

    assert result.errors is None
    data = result.data["dismissInsight"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "INVALID_INPUT"
    assert data["errors"][0]["field"] == "id"


def test_pin_insight_cross_workspace_id_returns_payload_not_found() -> None:
    insight = InsightFactory()
    other = InsightFactory()
    ctx = _session_ctx(workspace_pk=insight.workspace_id, allowed={"insights:pin"})

    result = _schema.execute_sync(
        PIN_MUTATION,
        variable_values={"id": _gid("InsightType", other.pk)},
        context_value=ctx,
    )

    assert result.errors is None
    data = result.data["pinInsight"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "NOT_FOUND"


def test_insight_permission_errors_use_payload() -> None:
    insight = InsightFactory()
    cases = (
        (DISMISS_MUTATION, "dismissInsight", {"insights:read"}),
        (PIN_MUTATION, "pinInsight", {"insights:read"}),
        (UNPIN_MUTATION, "unpinInsight", {"insights:read"}),
    )

    for mutation, field, allowed in cases:
        result = _schema.execute_sync(
            mutation,
            variable_values={"id": _gid("InsightType", insight.pk)},
            context_value=_session_ctx(workspace_pk=insight.workspace_id, allowed=allowed),
        )

        assert result.errors is None
        data = result.data[field]
        assert data["success"] is False
        assert data["errors"][0]["code"] == "PERMISSION_DENIED"
