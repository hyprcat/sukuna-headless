from __future__ import annotations

import uuid

import pytest
import strawberry
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.runs.api.queries import RunQuery
from apps.runs.factories import ConversationFactory, RunEventFactory, RunFactory
from apps.runs.tests.conftest import api_key_ctx, session_ctx
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q(RunQuery):
    pass


_schema = strawberry.Schema(query=_Q, extensions=[DjangoOptimizerExtension])


CONVERSATION_DETAIL_QUERY = """
query($id: ID!) {
    conversation(id: $id) {
        conversationUid
        title
        agentName
        agentId
        endUserExternalId
        runs(first: 10) {
            totalCount
            edges { node { runUid } }
        }
    }
}
"""

CONVERSATIONS_LIST_QUERY = """
query($agentId: Int) {
    conversations(agentId: $agentId, first: 10) {
        totalCount
        edges { node { conversationUid title agentName } }
    }
}
"""

RUN_WITH_CONVERSATION_QUERY = """
query($id: ID!) {
    run(id: $id) {
        runUid
        manifestId
        lastCallbackAt
        sandboxUrl
        conversation {
            conversationUid
            title
        }
    }
}
"""


def test_conversation_detail_returns_fields() -> None:
    conv = ConversationFactory(title="Multi-turn chat")
    run = RunFactory(finished=True, workspace=conv.workspace, agent=conv.agent, conversation=conv)

    result = _schema.execute_sync(
        CONVERSATION_DETAIL_QUERY,
        variable_values={"id": relay.to_base64("ConversationType", conv.pk)},
        context_value=session_ctx(conv.workspace),
    )

    assert result.errors is None
    data = result.data["conversation"]
    assert data["conversationUid"] == str(conv.conversation_uid)
    assert data["title"] == "Multi-turn chat"
    assert data["agentName"] == conv.agent.name
    assert data["agentId"] == relay.to_base64("AgentType", conv.agent_id)
    assert data["endUserExternalId"] == conv.end_user.external_user_id
    assert data["runs"]["totalCount"] == 1
    assert data["runs"]["edges"][0]["node"]["runUid"] == str(run.run_uid)


def test_conversation_detail_by_uid() -> None:
    conv = ConversationFactory()
    result = _schema.execute_sync(
        "query($uid: UUID!) { conversation(conversationUid: $uid) { conversationUid } }",
        variable_values={"uid": str(conv.conversation_uid)},
        context_value=session_ctx(conv.workspace),
    )
    assert result.errors is None
    assert result.data["conversation"]["conversationUid"] == str(conv.conversation_uid)


def test_conversation_detail_scoped_to_workspace() -> None:
    conv = ConversationFactory()
    other_ws = WorkspaceFactory()
    result = _schema.execute_sync(
        CONVERSATION_DETAIL_QUERY,
        variable_values={"id": relay.to_base64("ConversationType", conv.pk)},
        context_value=session_ctx(other_ws),
    )
    assert result.errors is None
    assert result.data["conversation"] is None


def test_conversations_list_returns_all_for_workspace() -> None:
    ws = WorkspaceFactory()
    c1 = ConversationFactory(workspace=ws)
    c2 = ConversationFactory(workspace=ws)
    ConversationFactory()  # other workspace

    result = _schema.execute_sync(
        CONVERSATIONS_LIST_QUERY,
        variable_values={},
        context_value=session_ctx(ws),
    )

    assert result.errors is None
    assert result.data["conversations"]["totalCount"] == 2
    uids = {e["node"]["conversationUid"] for e in result.data["conversations"]["edges"]}
    assert uids == {str(c1.conversation_uid), str(c2.conversation_uid)}


def test_conversations_list_filters_by_agent() -> None:
    ws = WorkspaceFactory()
    c1 = ConversationFactory(workspace=ws)
    ConversationFactory(workspace=ws)

    result = _schema.execute_sync(
        CONVERSATIONS_LIST_QUERY,
        variable_values={"agentId": c1.agent_id},
        context_value=session_ctx(ws),
    )

    assert result.errors is None
    assert result.data["conversations"]["totalCount"] == 1
    assert result.data["conversations"]["edges"][0]["node"]["conversationUid"] == str(
        c1.conversation_uid,
    )


def test_conversations_accessible_via_api_key() -> None:
    ws = WorkspaceFactory()
    ConversationFactory(workspace=ws)
    result = _schema.execute_sync(
        CONVERSATIONS_LIST_QUERY,
        variable_values={},
        context_value=api_key_ctx(ws, frozenset({"runs:read"})),
    )
    assert result.errors is None
    assert result.data["conversations"]["totalCount"] == 1


def test_conversations_rejected_without_scope() -> None:
    ws = WorkspaceFactory()
    ConversationFactory(workspace=ws)
    result = _schema.execute_sync(
        CONVERSATIONS_LIST_QUERY,
        variable_values={},
        context_value=api_key_ctx(ws, frozenset({"tools:read"})),
    )
    assert result.errors is not None
    assert "runs:read" in result.errors[0].message


def test_run_type_includes_new_fields() -> None:
    conv = ConversationFactory()
    run = RunFactory(
        running=True,
        workspace=conv.workspace,
        agent=conv.agent,
        conversation=conv,
        sandbox_id="sbx-abc123",
    )

    result = _schema.execute_sync(
        RUN_WITH_CONVERSATION_QUERY,
        variable_values={"id": relay.to_base64("RunType", run.pk)},
        context_value=session_ctx(run.workspace),
    )

    assert result.errors is None
    data = result.data["run"]
    assert data["conversation"]["conversationUid"] == str(conv.conversation_uid)
    assert data["conversation"]["title"] == conv.title
    assert data["manifestId"] is None
    assert data["lastCallbackAt"] is None
    assert data["sandboxUrl"] is not None
    assert "sbx-abc123" in data["sandboxUrl"]


def test_run_sandbox_url_null_when_terminal() -> None:
    run = RunFactory(finished=True, sandbox_id="sbx-abc123")
    result = _schema.execute_sync(
        RUN_WITH_CONVERSATION_QUERY,
        variable_values={"id": relay.to_base64("RunType", run.pk)},
        context_value=session_ctx(run.workspace),
    )
    assert result.errors is None
    assert result.data["run"]["sandboxUrl"] is None


def test_run_sandbox_url_null_when_queued() -> None:
    run = RunFactory(sandbox_id="sbx-abc123")
    result = _schema.execute_sync(
        RUN_WITH_CONVERSATION_QUERY,
        variable_values={"id": relay.to_base64("RunType", run.pk)},
        context_value=session_ctx(run.workspace),
    )
    assert result.errors is None
    assert result.data["run"]["sandboxUrl"] is None


def test_run_sandbox_url_null_when_no_sandbox_id() -> None:
    run = RunFactory(running=True, sandbox_id="")
    result = _schema.execute_sync(
        RUN_WITH_CONVERSATION_QUERY,
        variable_values={"id": relay.to_base64("RunType", run.pk)},
        context_value=session_ctx(run.workspace),
    )
    assert result.errors is None
    assert result.data["run"]["sandboxUrl"] is None


def test_run_conversation_null_when_unset() -> None:
    run = RunFactory(finished=True)
    result = _schema.execute_sync(
        RUN_WITH_CONVERSATION_QUERY,
        variable_values={"id": relay.to_base64("RunType", run.pk)},
        context_value=session_ctx(run.workspace),
    )
    assert result.errors is None
    assert result.data["run"]["conversation"] is None


def test_run_event_includes_callback_fields() -> None:
    run = RunFactory(running=True)
    cb_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    RunEventFactory(
        run=run,
        sequence_no=1,
        event_type="run_started",
        callback_event_id=cb_id,
        batch_id=batch_id,
    )

    result = _schema.execute_sync(
        """
        query($id: ID!) {
            run(id: $id) {
                events(first: 1) {
                    edges { node { callbackEventId batchId } }
                }
            }
        }
        """,
        variable_values={"id": relay.to_base64("RunType", run.pk)},
        context_value=session_ctx(run.workspace),
    )

    assert result.errors is None
    node = result.data["run"]["events"]["edges"][0]["node"]
    assert node["callbackEventId"] == str(cb_id)
    assert node["batchId"] == str(batch_id)


def test_conversation_end_user_null_when_unset() -> None:
    conv = ConversationFactory(end_user=None)
    result = _schema.execute_sync(
        CONVERSATION_DETAIL_QUERY,
        variable_values={"id": relay.to_base64("ConversationType", conv.pk)},
        context_value=session_ctx(conv.workspace),
    )
    assert result.errors is None
    assert result.data["conversation"]["endUserExternalId"] is None
