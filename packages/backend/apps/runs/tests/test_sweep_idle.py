from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.utils import timezone

from apps.runs.factories import (
    ConversationFactory,
    RunEventFactory,
    RunFactory,
    SandboxInstanceFactory,
)
from apps.runs.models.sandbox_instance import SandboxState
from apps.runs.tasks.sweep_idle import sweep_idle_sandboxes

pytestmark = pytest.mark.django_db(transaction=True)

_BIG = 1200  # seconds — well past any idle threshold


@patch("apps.runs.tasks.sweep_idle.runtime")
@patch("apps.runs.tasks.sweep_idle.e2b.terminate_sandbox", new_callable=AsyncMock)
def test_idle_paused_sandbox_is_terminated(
    mock_terminate: AsyncMock, mock_runtime: MagicMock
) -> None:
    mock_runtime.sandbox_max_idle_seconds = 600

    instance = SandboxInstanceFactory(
        paused=True,
        last_run_finished_at=timezone.now() - timedelta(seconds=_BIG),
    )

    count = sweep_idle_sandboxes()

    assert count == 1
    mock_terminate.assert_awaited_once_with(instance.sandbox_id)
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.TERMINATED


@patch("apps.runs.tasks.sweep_idle.runtime")
@patch("apps.runs.tasks.sweep_idle.e2b.terminate_sandbox", new_callable=AsyncMock)
def test_running_sandbox_is_skipped(mock_terminate: AsyncMock, mock_runtime: MagicMock) -> None:
    mock_runtime.sandbox_max_idle_seconds = 600

    SandboxInstanceFactory(
        running=True,
        last_run_finished_at=timezone.now() - timedelta(seconds=_BIG),
    )

    count = sweep_idle_sandboxes()

    assert count == 0
    mock_terminate.assert_not_awaited()


@patch("apps.runs.tasks.sweep_idle.runtime")
@patch("apps.runs.tasks.sweep_idle.e2b.terminate_sandbox", new_callable=AsyncMock)
def test_recently_paused_sandbox_is_skipped(
    mock_terminate: AsyncMock, mock_runtime: MagicMock
) -> None:
    mock_runtime.sandbox_max_idle_seconds = 600

    # last_run_finished_at is recent — not past the idle threshold
    SandboxInstanceFactory(paused=True)

    count = sweep_idle_sandboxes()

    assert count == 0
    mock_terminate.assert_not_awaited()


@patch("apps.runs.tasks.sweep_idle.runtime")
@patch("apps.runs.tasks.sweep_idle.e2b.terminate_sandbox", new_callable=AsyncMock)
def test_pending_hitl_sandbox_is_skipped(
    mock_terminate: AsyncMock, mock_runtime: MagicMock
) -> None:
    mock_runtime.sandbox_max_idle_seconds = 600

    conversation = ConversationFactory()
    conv_uid = conversation.conversation_uid

    run = RunFactory(running=True, conversation=conversation)
    RunEventFactory(run=run, event_type="hitl_requested")

    instance = SandboxInstanceFactory(
        paused=True,
        last_run_finished_at=timezone.now() - timedelta(seconds=_BIG),
        conversation_id=conv_uid,
    )

    count = sweep_idle_sandboxes()

    assert count == 0
    mock_terminate.assert_not_awaited()
    instance.refresh_from_db()
    assert instance.sandbox_state == SandboxState.PAUSED
