from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.agents.factories import AgentFactory
from apps.billing.schemas import BillingFormat
from apps.core.exceptions import Conflict
from apps.end_users.factories import EndUserFactory
from apps.runs.factories import ArtifactFactory, ConversationFactory, RunEventFactory, RunFactory
from apps.runs.models import ArtifactKind, Conversation, Rating, Run, RunEvent
from apps.runs.schemas.events import RunStatus
from apps.runs.schemas.lease import Lease
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


# -- Run creation and defaults --


def test_run_created_with_queued_status() -> None:
    run = RunFactory()
    assert run.status == RunStatus.QUEUED
    assert run.started_at is None
    assert run.finished_at is None
    assert run.total_cost_usd == Decimal("0")
    assert run.total_tokens == 0
    assert not run.is_terminal


# -- Lease --


def test_set_and_read_lease() -> None:
    run = RunFactory()
    lease = Lease(max_runtime_seconds=600, max_total_tokens=50_000, max_cost_usd=Decimal("5.00"))
    run.set_lease(lease)
    run.refresh_from_db()
    restored = run.lease
    assert restored is not None
    assert restored.max_runtime_seconds == 600
    assert restored.max_total_tokens == 50_000
    assert restored.max_cost_usd == Decimal("5.00")


# -- Cancel --


def test_cancel_transitions_active_run() -> None:
    run = RunFactory(running=True)
    run.cancel()
    run.refresh_from_db()
    assert run.status == RunStatus.CANCELLED
    assert run.finished_at is not None
    state = run.projected_state
    assert state is not None
    assert state.status == RunStatus.CANCELLED


def test_cancel_rejects_terminal_run() -> None:
    run = RunFactory(finished=True)
    with pytest.raises(Conflict, match="already"):
        run.cancel()


# -- QuerySet --


def test_active_queryset_filters_non_terminal() -> None:
    ws = RunFactory(running=True).workspace
    RunFactory(workspace=ws, finished=True)
    RunFactory(workspace=ws)
    active = Run.objects.for_workspace(ws.pk).active()
    assert active.count() == 2


def test_terminal_queryset_filters_completed() -> None:
    ws = RunFactory(finished=True).workspace
    RunFactory(workspace=ws, running=True)
    RunFactory(workspace=ws, failed=True)
    terminal = Run.objects.for_workspace(ws.pk).terminal()
    assert terminal.count() == 2


def test_active_count_for_end_user() -> None:
    run = RunFactory(running=True)
    RunFactory(workspace=run.workspace, end_user=run.end_user, running=True)
    RunFactory(workspace=run.workspace, end_user=run.end_user, finished=True)
    assert Run.objects.active_count_for_end_user(run.end_user_id) == 2


# -- Cost constraint --


def test_negative_cost_blocked_by_constraint() -> None:
    run = RunFactory()
    run.total_cost_usd = Decimal("-1.00")
    with pytest.raises(IntegrityError):
        run.save(update_fields=("total_cost_usd",))


# -- Artifact --


def test_artifact_creation() -> None:
    artifact = ArtifactFactory(kind=ArtifactKind.CODE, name="main.py")
    assert artifact.kind == ArtifactKind.CODE
    assert artifact.name == "main.py"
    assert artifact.run is not None


def test_artifact_belongs_to_run() -> None:
    run = RunFactory(finished=True)
    a1 = ArtifactFactory(run=run)
    a2 = ArtifactFactory(run=run)
    assert run.artifacts.count() == 2
    assert set(run.artifacts.values_list("pk", flat=True)) == {a1.pk, a2.pk}


# -- Rating --


def test_rating_submit_on_finished_run() -> None:
    run = RunFactory(finished=True)
    rating = Rating.submit(run.pk, score=5, comment="Great work")
    assert rating.score == 5
    assert rating.comment == "Great work"
    assert rating.run_id == run.pk


def test_rating_rejects_duplicate() -> None:
    run = RunFactory(finished=True)
    Rating.submit(run.pk, score=4)
    with pytest.raises(Conflict, match="already been rated"):
        Rating.submit(run.pk, score=3)


def test_rating_rejects_active_run() -> None:
    run = RunFactory(running=True)
    with pytest.raises(Conflict, match="completed runs"):
        Rating.submit(run.pk, score=4)


# -- Run field additions (Phase 8C) --


def test_run_new_fields_default_values() -> None:
    run = RunFactory()
    assert run.conversation is None
    assert run.manifest_id is None
    assert run.last_callback_at is None
    assert run.last_projected_sequence == 0


def test_run_for_conversation_queryset() -> None:
    conv = ConversationFactory()
    RunFactory(
        workspace=conv.workspace,
        agent=conv.agent,
        end_user=conv.end_user,
        conversation=conv,
    )
    RunFactory()  # different conversation
    assert Run.objects.for_conversation(conv.pk).count() == 1


# -- RunEvent field additions (Phase 8C) --


def test_runevent_callback_event_id_unique() -> None:
    uid = uuid.uuid4()
    RunEventFactory(callback_event_id=uid)
    with pytest.raises(IntegrityError):
        RunEventFactory(callback_event_id=uid)


def test_runevent_multiple_null_callback_ids() -> None:
    run = RunFactory(running=True)
    e1 = RunEventFactory(run=run, sequence_no=1, callback_event_id=None)
    e2 = RunEventFactory(run=run, sequence_no=2, callback_event_id=None)
    assert e1.callback_event_id is None
    assert e2.callback_event_id is None
    assert RunEvent.objects.filter(run=run).count() == 2


# -- Cost currency --


def test_run_cost_stores_currency_code() -> None:
    run = RunFactory()
    assert run.total_cost_currency == BillingFormat().currency


def test_run_cost_currency_constraint_blocks_non_usd_writes() -> None:
    run = RunFactory()
    run.total_cost_currency = "EUR"
    with pytest.raises(IntegrityError), transaction.atomic():
        run.save(update_fields=("total_cost_currency",))


# -- Conversation --


def test_conversation_default_uid_generated() -> None:
    conv = ConversationFactory()
    assert conv.conversation_uid is not None


def test_conversation_title_stored() -> None:
    conv = ConversationFactory(title="Debug session #3")
    conv.refresh_from_db()
    assert conv.title == "Debug session #3"


def test_conversation_rejects_agent_from_different_workspace() -> None:
    workspace = WorkspaceFactory()
    agent = AgentFactory()
    with pytest.raises(ValidationError, match="Agent must belong"):
        ConversationFactory(workspace=workspace, agent=agent)


def test_conversation_rejects_end_user_from_different_workspace() -> None:
    workspace = WorkspaceFactory()
    agent = AgentFactory(workspace=workspace)
    end_user = EndUserFactory()
    with pytest.raises(ValidationError, match="End user must belong"):
        ConversationFactory(workspace=workspace, agent=agent, end_user=end_user)


def test_conversation_end_user_set_null_on_delete() -> None:
    conv = ConversationFactory()
    conv.end_user.delete()
    conv.refresh_from_db()
    assert conv.end_user is None
    assert Conversation.objects.filter(pk=conv.pk).exists()


def test_conversation_for_workspace() -> None:
    ws = WorkspaceFactory()
    agent = AgentFactory(workspace=ws)
    ConversationFactory(workspace=ws, agent=agent)
    ConversationFactory()
    assert Conversation.objects.for_workspace(ws.pk).count() == 1


def test_conversation_for_agent() -> None:
    ws = WorkspaceFactory()
    a1 = AgentFactory(workspace=ws)
    a2 = AgentFactory(workspace=ws)
    ConversationFactory(workspace=ws, agent=a1)
    ConversationFactory(workspace=ws, agent=a2)
    assert Conversation.objects.for_agent(a1.pk).count() == 1


def test_conversation_for_end_user() -> None:
    ws = WorkspaceFactory()
    agent = AgentFactory(workspace=ws)
    eu1 = EndUserFactory(workspace=ws)
    eu2 = EndUserFactory(workspace=ws)
    ConversationFactory(workspace=ws, agent=agent, end_user=eu1)
    ConversationFactory(workspace=ws, agent=agent, end_user=eu2)
    assert Conversation.objects.for_end_user(eu1.pk).count() == 1


def test_run_conversation_fk() -> None:
    conv = ConversationFactory()
    run = RunFactory(
        workspace=conv.workspace,
        agent=conv.agent,
        end_user=conv.end_user,
        conversation=conv,
    )
    assert run.conversation_id == conv.pk
    assert run.conversation.conversation_uid == conv.conversation_uid


def test_run_conversation_nullable() -> None:
    run = RunFactory(conversation=None)
    assert run.conversation is None


def test_conversation_set_null_on_run_delete() -> None:
    conv = ConversationFactory()
    run = RunFactory(
        workspace=conv.workspace,
        agent=conv.agent,
        end_user=conv.end_user,
        conversation=conv,
    )
    conv.delete()
    run.refresh_from_db()
    assert run.conversation is None
