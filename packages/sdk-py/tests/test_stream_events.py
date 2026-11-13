"""Unit tests for ``parse_stream_event`` and ``is_terminal_type``.

Ports ``sdk-ts/test/stream-events.test.ts`` to Python.
"""

from __future__ import annotations

import json

from midsphere.run.events import (
    TERMINAL_EVENT_TYPES,
    StreamEvent,
    is_terminal_type,
    parse_stream_event,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _data(obj: object) -> str:
    """Serialise an object to a JSON string (the SSE ``data`` field)."""
    return json.dumps(obj)


def _valid_event(**overrides: object) -> str:
    """Return a valid SSE data string with optional field overrides."""
    base: dict[str, object] = {
        "event_id": "e1",
        "sequence_no": 7,
        "event_type": "run_started",
        "payload": {"model_tier": "pro", "sandbox_id": "sb1"},
        "emitted_at": "2026-06-21T00:00:00Z",
    }
    base.update(overrides)
    return _data(base)


# ---------------------------------------------------------------------------
# Parsing happy path
# ---------------------------------------------------------------------------


def test_parses_known_event_into_stream_event() -> None:
    """A well-formed SSE data string produces a populated ``StreamEvent``."""
    evt = parse_stream_event(_valid_event())

    assert evt is not None
    assert isinstance(evt, StreamEvent)
    assert evt.type == "run_started"
    assert evt.event_id == "e1"
    assert evt.sequence_no == 7
    assert evt.emitted_at == "2026-06-21T00:00:00Z"
    assert evt.payload == {"model_tier": "pro", "sandbox_id": "sb1"}


def test_payload_absent_defaults_to_empty_dict() -> None:
    """Missing ``payload`` key is tolerated; defaults to ``{}``."""
    raw = {
        "event_id": "e1",
        "sequence_no": 1,
        "event_type": "run_started",
        "emitted_at": "2026-06-21T00:00:00Z",
    }
    evt = parse_stream_event(_data(raw))
    assert evt is not None
    assert evt.payload == {}


def test_payload_null_defaults_to_empty_dict() -> None:
    """``payload: null`` is coerced to ``{}``."""
    evt = parse_stream_event(_valid_event(payload=None))
    assert evt is not None
    assert evt.payload == {}


# ---------------------------------------------------------------------------
# None-return cases
# ---------------------------------------------------------------------------


def test_returns_none_for_empty_string() -> None:
    assert parse_stream_event("") is None


def test_returns_none_for_whitespace_only() -> None:
    assert parse_stream_event("   \n  ") is None


def test_returns_none_for_invalid_json() -> None:
    assert parse_stream_event("not json {") is None


def test_returns_none_for_json_string() -> None:
    assert parse_stream_event('"just a string"') is None


def test_returns_none_for_json_array() -> None:
    assert parse_stream_event("[]") is None


def test_returns_none_for_json_number() -> None:
    assert parse_stream_event("42") is None


def test_returns_none_for_missing_event_type() -> None:
    raw = {
        "event_id": "e1",
        "sequence_no": 1,
        "emitted_at": "2026-06-21T00:00:00Z",
    }
    assert parse_stream_event(_data(raw)) is None


def test_returns_none_for_unknown_event_type() -> None:
    """Forward-compat: an unknown/future event type is silently skipped."""
    assert parse_stream_event(_valid_event(event_type="some_future_event")) is None


def test_returns_none_for_numeric_event_type() -> None:
    assert parse_stream_event(_valid_event(event_type=42)) is None


def test_returns_none_for_non_int_sequence_no() -> None:
    assert parse_stream_event(_valid_event(sequence_no="seven")) is None


def test_returns_none_for_float_sequence_no() -> None:
    assert parse_stream_event(_valid_event(sequence_no=1.5)) is None


def test_returns_none_for_missing_event_id() -> None:
    raw = {
        "sequence_no": 1,
        "event_type": "run_started",
        "payload": {},
        "emitted_at": "2026-06-21T00:00:00Z",
    }
    assert parse_stream_event(_data(raw)) is None


def test_returns_none_for_non_string_event_id() -> None:
    assert parse_stream_event(_valid_event(event_id=99)) is None


def test_returns_none_for_missing_emitted_at() -> None:
    raw = {
        "event_id": "e1",
        "sequence_no": 1,
        "event_type": "run_started",
        "payload": {},
    }
    assert parse_stream_event(_data(raw)) is None


def test_returns_none_for_non_string_emitted_at() -> None:
    assert parse_stream_event(_valid_event(emitted_at=12345)) is None


# ---------------------------------------------------------------------------
# Terminal-event detection
# ---------------------------------------------------------------------------


def test_is_terminal_type_true_for_all_three_terminal_types() -> None:
    assert is_terminal_type("run_completed") is True
    assert is_terminal_type("run_failed") is True
    assert is_terminal_type("run_cancelled") is True


def test_is_terminal_type_false_for_non_terminal() -> None:
    assert is_terminal_type("run_started") is False
    assert is_terminal_type("tool_call") is False
    assert is_terminal_type("tool_result") is False
    assert is_terminal_type("usage_checkpoint") is False
    assert is_terminal_type("step") is False


def test_terminal_event_types_constant_has_exactly_three_entries() -> None:
    assert set(TERMINAL_EVENT_TYPES) == {"run_completed", "run_failed", "run_cancelled"}


def test_stream_event_is_terminal_property_true() -> None:
    """``StreamEvent.is_terminal`` is ``True`` for a terminal event."""
    raw = _data(
        {
            "event_id": "e",
            "sequence_no": 1,
            "event_type": "run_completed",
            "payload": {
                "final_usage": {"runtime_seconds": 1, "total_tokens": 1, "cost_usd": "0.01"},
                "summary": "",
            },
            "emitted_at": "2026-06-21T00:00:00Z",
        }
    )
    evt = parse_stream_event(raw)
    assert evt is not None
    assert evt.is_terminal is True


def test_stream_event_is_terminal_property_false() -> None:
    """``StreamEvent.is_terminal`` is ``False`` for a non-terminal event."""
    evt = parse_stream_event(_valid_event())
    assert evt is not None
    assert evt.is_terminal is False


def test_is_terminal_property_for_run_failed() -> None:
    raw = _data(
        {
            "event_id": "e",
            "sequence_no": 2,
            "event_type": "run_failed",
            "payload": {
                "error_code": "TIMEOUT",
                "message": "timed out",
                "final_usage": {"runtime_seconds": 5, "total_tokens": 10, "cost_usd": "0.01"},
            },
            "emitted_at": "2026-06-21T00:00:00Z",
        }
    )
    evt = parse_stream_event(raw)
    assert evt is not None
    assert evt.is_terminal is True


def test_is_terminal_property_for_run_cancelled() -> None:
    raw = _data(
        {
            "event_id": "e",
            "sequence_no": 3,
            "event_type": "run_cancelled",
            "payload": {
                "reason": "user",
                "final_usage": {"runtime_seconds": 1, "total_tokens": 5, "cost_usd": "0.00"},
            },
            "emitted_at": "2026-06-21T00:00:00Z",
        }
    )
    evt = parse_stream_event(raw)
    assert evt is not None
    assert evt.is_terminal is True
