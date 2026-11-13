from __future__ import annotations

import pytest
import strawberry
from django.db import connection
from django.test.utils import CaptureQueriesContext
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.end_users.factories import EndUserFactory
from apps.runs.api.queries import RunQuery
from apps.runs.factories import RatingFactory, RunEventFactory, RunFactory
from apps.runs.tests.conftest import api_key_ctx, session_ctx
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q(RunQuery):
    pass


_schema = strawberry.Schema(query=_Q, extensions=[DjangoOptimizerExtension])


def _global_run_id(run: object) -> str:
    return relay.to_base64("RunType", run.pk)  # type: ignore[attr-defined]


RUN_DETAIL_QUERY = """
query($id: ID!) {
    run(id: $id) {
        runUid
        agentId
        agentName
        endUserIdExternal
        promptPreview
        rating { score comment }
        events(first: 2) {
            totalCount
            edges { node { sequenceNo eventType payload } }
        }
    }
}
"""


def test_run_detail_returns_events_and_rating() -> None:
    run = RunFactory(finished=True, prompt="Summarize the account renewal history.")
    RatingFactory(run=run, score=5, comment="Useful")
    _event(run, 1, "run_started")
    _event(run, 2, "run_usage")
    _event(run, 3, "run_finished")

    with CaptureQueriesContext(connection) as queries:
        result = _schema.execute_sync(
            RUN_DETAIL_QUERY,
            variable_values={"id": _global_run_id(run)},
            context_value=session_ctx(run.workspace),
        )

    assert result.errors is None
    data = result.data["run"]
    assert data["agentId"] == relay.to_base64("AgentType", run.agent_id)
    assert data["rating"] == {"score": 5, "comment": "Useful"}
    assert data["events"]["totalCount"] == 3
    assert [edge["node"]["sequenceNo"] for edge in data["events"]["edges"]] == [1, 2]
    assert len(queries) <= 5


def test_run_detail_returns_null_for_unrated_run() -> None:
    run = RunFactory(finished=True)
    result = _schema.execute_sync(
        RUN_DETAIL_QUERY,
        variable_values={"id": _global_run_id(run)},
        context_value=session_ctx(run.workspace),
    )
    assert result.errors is None
    assert result.data["run"]["rating"] is None


def test_run_detail_accepts_existing_run_uid_argument() -> None:
    run = RunFactory(finished=True)
    result = _schema.execute_sync(
        "query($runUid: UUID!) { run(runUid: $runUid) { runUid } }",
        variable_values={"runUid": str(run.run_uid)},
        context_value=session_ctx(run.workspace),
    )
    assert result.errors is None
    assert result.data["run"]["runUid"] == str(run.run_uid)


def test_run_detail_accepts_raw_uuid_id() -> None:
    run = RunFactory(finished=True)
    result = _schema.execute_sync(
        RUN_DETAIL_QUERY,
        variable_values={"id": str(run.run_uid)},
        context_value=session_ctx(run.workspace),
    )
    assert result.errors is None
    assert result.data["run"]["runUid"] == str(run.run_uid)


def test_run_detail_rejects_wrong_global_id_type() -> None:
    ws = WorkspaceFactory()
    result = _schema.execute_sync(
        RUN_DETAIL_QUERY,
        variable_values={"id": relay.to_base64("AgentType", 1)},
        context_value=session_ctx(ws),
    )
    assert result.errors is None
    assert result.data["run"] is None


def test_run_detail_cannot_select_another_workspace_run() -> None:
    ws = WorkspaceFactory()
    other_run = RunFactory(finished=True)
    result = _schema.execute_sync(
        RUN_DETAIL_QUERY,
        variable_values={"id": _global_run_id(other_run)},
        context_value=session_ctx(ws),
    )
    assert result.errors is None
    assert result.data["run"] is None


def test_run_detail_allows_api_key_with_runs_read_scope() -> None:
    run = RunFactory(finished=True)
    result = _schema.execute_sync(
        RUN_DETAIL_QUERY,
        variable_values={"id": _global_run_id(run)},
        context_value=api_key_ctx(run.workspace, frozenset({"runs:read"})),
    )
    assert result.errors is None
    assert result.data["run"]["runUid"] == str(run.run_uid)


def test_run_detail_rejects_api_key_without_runs_read_scope() -> None:
    run = RunFactory(finished=True)
    result = _schema.execute_sync(
        RUN_DETAIL_QUERY,
        variable_values={"id": _global_run_id(run)},
        context_value=api_key_ctx(run.workspace, frozenset({"tools:read"})),
    )
    assert result.errors is not None
    assert "runs:read" in result.errors[0].message


def test_run_list_filters_by_end_user_and_includes_rating() -> None:
    workspace = WorkspaceFactory()
    end_user = EndUserFactory(workspace=workspace)
    included = RunFactory(finished=True, workspace=workspace, end_user=end_user)
    RatingFactory(run=included, score=4)
    RunFactory(finished=True, workspace=workspace)

    result = _schema.execute_sync(
        """
        query($endUserId: Int) {
            runs(endUserId: $endUserId, first: 10) {
                edges { node { runUid rating { score } endUserIdExternal } }
            }
        }
        """,
        variable_values={"endUserId": end_user.pk},
        context_value=session_ctx(workspace),
    )

    assert result.errors is None
    nodes = [edge["node"] for edge in result.data["runs"]["edges"]]
    assert nodes == [
        {
            "runUid": str(included.run_uid),
            "rating": {"score": 4},
            "endUserIdExternal": end_user.external_user_id,
        }
    ]


def _event(run: object, sequence_no: int, event_type: str) -> None:
    RunEventFactory(
        run=run,
        sequence_no=sequence_no,
        event_type=event_type,
        payload={"type": event_type, "sequence_no": sequence_no},
    )
