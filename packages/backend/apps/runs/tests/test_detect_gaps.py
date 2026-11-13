from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.runs.factories import RunEventFactory, RunFactory
from apps.runs.tasks.detect_gaps import detect_callback_gaps

pytestmark = pytest.mark.django_db(transaction=True)


class TestDetectCallbackGaps:
    def test_gap_detected_and_event_emitted(self):
        now = timezone.now()
        run = RunFactory(
            running=True,
            last_callback_at=now - timedelta(minutes=15),
        )
        for seq in (1, 2, 5):
            RunEventFactory(run=run, sequence_no=seq, event_type="run_usage", payload={})

        with patch("apps.runs.tasks.detect_gaps.record_event") as mock_record:
            count = detect_callback_gaps()

        assert count == 1
        mock_record.assert_called_once_with(
            "callback_gap_detected",
            distinct_id=str(run.workspace_id),
            properties={"run_id": str(run.run_uid), "max_sequence": 5, "present_count": 3},
        )

    def test_no_gap_run_skipped(self):
        run = RunFactory(running=True)
        for seq in (1, 2, 3):
            RunEventFactory(run=run, sequence_no=seq, event_type="run_usage", payload={})

        with patch("apps.runs.tasks.detect_gaps.record_event") as mock_record:
            count = detect_callback_gaps()

        assert count == 0
        mock_record.assert_not_called()

    def test_gap_not_persistent_no_event_emitted(self):
        now = timezone.now()
        run = RunFactory(
            running=True,
            last_callback_at=now - timedelta(minutes=2),
        )
        for seq in (1, 3):
            RunEventFactory(run=run, sequence_no=seq, event_type="run_usage", payload={})

        with patch("apps.runs.tasks.detect_gaps.record_event") as mock_record:
            count = detect_callback_gaps()

        assert count == 1
        mock_record.assert_not_called()

    def test_run_with_no_events_skipped(self):
        RunFactory(running=True)

        with patch("apps.runs.tasks.detect_gaps.record_event") as mock_record:
            count = detect_callback_gaps()

        assert count == 0
        mock_record.assert_not_called()
