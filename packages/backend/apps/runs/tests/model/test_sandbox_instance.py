from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.agents.factories import AgentFactory
from apps.core.exceptions import Conflict
from apps.runs.factories import ConversationFactory, RunFactory, SandboxInstanceFactory
from apps.runs.models import SandboxInstance, SandboxState

pytestmark = pytest.mark.django_db


# -- Creation and defaults --


def test_created_with_spawning_state() -> None:
    instance = SandboxInstanceFactory()
    assert instance.sandbox_state == SandboxState.SPAWNING
    assert instance.current_run is None
    assert instance.pause_count == 0
    assert instance.resume_count == 0


def test_sandbox_id_is_unique() -> None:
    instance = SandboxInstanceFactory()
    with pytest.raises(IntegrityError):
        SandboxInstanceFactory(sandbox_id=instance.sandbox_id)


# -- State transition: mark_booted --


def test_mark_booted_from_booting() -> None:
    instance = SandboxInstanceFactory(booting=True)
    instance.mark_booted()
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.RUNNING
    assert instance.boot_completed_at is not None


def test_mark_booted_rejects_from_spawning() -> None:
    instance = SandboxInstanceFactory()
    with pytest.raises(Conflict, match="Cannot transition"):
        instance.mark_booted()


def test_mark_booted_rejects_from_terminated() -> None:
    instance = SandboxInstanceFactory(terminated=True)
    with pytest.raises(Conflict, match="Cannot transition"):
        instance.mark_booted()


# -- State transition: mark_running --


def test_mark_running_from_paused() -> None:
    instance = SandboxInstanceFactory(paused=True)
    run = RunFactory(workspace=instance.workspace, agent=instance.agent)
    initial_resume = instance.resume_count
    instance.mark_running(run)
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.RUNNING
    assert instance.current_run == run
    assert instance.resume_count == initial_resume + 1


def test_mark_running_from_booting() -> None:
    instance = SandboxInstanceFactory(booting=True)
    run = RunFactory(workspace=instance.workspace, agent=instance.agent)
    instance.mark_running(run)
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.RUNNING
    assert instance.current_run == run


def test_mark_running_rejects_from_spawning() -> None:
    instance = SandboxInstanceFactory()
    run = RunFactory(workspace=instance.workspace, agent=instance.agent)
    with pytest.raises(Conflict, match="Cannot transition"):
        instance.mark_running(run)


def test_mark_running_rejects_from_terminated() -> None:
    instance = SandboxInstanceFactory(terminated=True)
    run = RunFactory(workspace=instance.workspace, agent=instance.agent)
    with pytest.raises(Conflict, match="Cannot transition"):
        instance.mark_running(run)


def test_mark_running_rejects_cross_workspace_run() -> None:
    instance = SandboxInstanceFactory(paused=True)
    run = RunFactory()
    with pytest.raises(Conflict, match="workspace"):
        instance.mark_running(run)


def test_mark_running_rejects_different_agent() -> None:
    instance = SandboxInstanceFactory(paused=True)
    run = RunFactory(
        workspace=instance.workspace,
        agent=AgentFactory(workspace=instance.workspace),
    )
    with pytest.raises(Conflict, match="agent"):
        instance.mark_running(run)


def test_mark_running_rejects_different_conversation() -> None:
    conversation = ConversationFactory()
    instance = SandboxInstanceFactory(
        paused=True,
        workspace=conversation.workspace,
        agent=conversation.agent,
        conversation_id=uuid.uuid4(),
    )
    run = RunFactory(
        workspace=conversation.workspace,
        agent=conversation.agent,
        end_user=conversation.end_user,
        conversation=conversation,
    )
    with pytest.raises(Conflict, match="conversation"):
        instance.mark_running(run)


# -- State transition: mark_paused --


def test_mark_paused_from_running() -> None:
    instance = SandboxInstanceFactory(running=True)
    instance.mark_paused()
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.PAUSED
    assert instance.current_run is None
    assert instance.last_run_finished_at is not None
    assert instance.pause_count == 1


def test_mark_paused_rejects_from_spawning() -> None:
    instance = SandboxInstanceFactory()
    with pytest.raises(Conflict, match="Cannot transition"):
        instance.mark_paused()


def test_mark_paused_rejects_from_terminated() -> None:
    instance = SandboxInstanceFactory(terminated=True)
    with pytest.raises(Conflict, match="Cannot transition"):
        instance.mark_paused()


# -- State transition: mark_terminated --


def test_mark_terminated_from_running() -> None:
    instance = SandboxInstanceFactory(running=True)
    instance.mark_terminated()
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.TERMINATED
    assert instance.current_run is None


def test_mark_terminated_from_paused() -> None:
    instance = SandboxInstanceFactory(paused=True)
    instance.mark_terminated()
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.TERMINATED


def test_mark_terminated_from_spawning() -> None:
    instance = SandboxInstanceFactory()
    instance.mark_terminated()
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.TERMINATED


def test_mark_terminated_from_booting() -> None:
    instance = SandboxInstanceFactory(booting=True)
    instance.mark_terminated()
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.TERMINATED


def test_mark_terminated_rejects_from_terminated() -> None:
    instance = SandboxInstanceFactory(terminated=True)
    with pytest.raises(Conflict, match="Cannot transition"):
        instance.mark_terminated()


# -- QuerySet filters --


def test_warm_returns_paused_without_run() -> None:
    warm = SandboxInstanceFactory(paused=True)
    SandboxInstanceFactory(running=True)
    SandboxInstanceFactory(terminated=True)
    SandboxInstanceFactory()

    qs = SandboxInstance.objects.warm()
    assert list(qs) == [warm]


def test_for_agent_filters_correctly() -> None:
    instance = SandboxInstanceFactory()
    SandboxInstanceFactory()

    qs = SandboxInstance.objects.for_agent(instance.agent_id)
    assert qs.count() == 1
    assert qs.first() == instance


def test_for_conversation_filters_correctly() -> None:
    conv_id = uuid.uuid4()
    instance = SandboxInstanceFactory(conversation_id=conv_id)
    SandboxInstanceFactory()

    qs = SandboxInstance.objects.for_conversation(str(conv_id))
    assert qs.count() == 1
    assert qs.first() == instance


def test_idle_past_filters_correctly() -> None:
    old = SandboxInstanceFactory(paused=True)
    old.last_run_finished_at = timezone.now() - timedelta(seconds=700)
    old.save(update_fields=("last_run_finished_at",))

    recent = SandboxInstanceFactory(paused=True)
    recent.last_run_finished_at = timezone.now() - timedelta(seconds=100)
    recent.save(update_fields=("last_run_finished_at",))

    qs = SandboxInstance.objects.idle_past(600)
    assert old in qs
    assert recent not in qs


def test_for_workspace_filters_correctly() -> None:
    instance = SandboxInstanceFactory()
    SandboxInstanceFactory()

    qs = SandboxInstance.objects.for_workspace(instance.workspace_id)
    assert qs.count() == 1
    assert qs.first() == instance
