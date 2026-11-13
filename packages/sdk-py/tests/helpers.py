"""Shared test helpers for the midsphere Python SDK test suite.

Imported by parallel test modules as ``from helpers import ...``.
pytest's default prepend import mode puts ``tests/`` on sys.path so no
``__init__.py`` is required.
"""

from __future__ import annotations

import json

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUN_UID = "11111111-1111-1111-1111-111111111111"
RUN_ID = "UnVuVHlwZToxMjM="
SANDBOX_URL = "https://sb1.run.midsphere.com"
BASE_URL = "https://api.midsphere.com"
GRAPHQL_URL = "https://api.midsphere.com/graphql/"
API_KEY = "ms_test_x"

# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def sse_bytes(events: list[dict]) -> bytes:  # type: ignore[type-arg]
    """Build a ``text/event-stream`` body from a list of event dicts."""
    lines = []
    for e in events:
        lines.append(f"id: {e['sequence_no']}\nevent: {e['event_type']}\ndata: {json.dumps(e)}\n\n")
    return "".join(lines).encode("utf-8")


def happy_path_events() -> list[dict]:  # type: ignore[type-arg]
    """Return the canonical 5-event happy-path sequence (mirrors the TS original)."""
    return [
        {
            "event_id": "e1",
            "sequence_no": 1,
            "event_type": "run_started",
            "payload": {"model_tier": "pro", "sandbox_id": "sb1"},
            "emitted_at": "2026-06-21T00:00:00Z",
        },
        {
            "event_id": "e2",
            "sequence_no": 2,
            "event_type": "tool_call",
            "payload": {
                "call_id": "c1",
                "tool_name": "search",
                "arguments": {"q": "x"},
                "is_mcp": False,
            },
            "emitted_at": "2026-06-21T00:00:01Z",
        },
        {
            "event_id": "e3",
            "sequence_no": 3,
            "event_type": "tool_result",
            "payload": {
                "call_id": "c1",
                "tool_name": "search",
                "result": "ok",
                "duration_ms": 12,
            },
            "emitted_at": "2026-06-21T00:00:02Z",
        },
        {
            "event_id": "e4",
            "sequence_no": 4,
            "event_type": "usage_checkpoint",
            "payload": {
                "runtime_seconds": 5,
                "total_tokens": 50,
                "cost_usd": "0.20",
                "tool_calls_count": 1,
            },
            "emitted_at": "2026-06-21T00:00:03Z",
        },
        {
            "event_id": "e5",
            "sequence_no": 5,
            "event_type": "run_completed",
            "payload": {
                "final_usage": {
                    "runtime_seconds": 10,
                    "total_tokens": 100,
                    "cost_usd": "0.40",
                },
                "summary": "done",
            },
            "emitted_at": "2026-06-21T00:00:04Z",
        },
    ]


def sse_response(events: list[dict]) -> httpx.Response:  # type: ignore[type-arg]
    """Return an ``httpx.Response`` with ``text/event-stream`` content."""
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse_bytes(events),
    )


def graphql_response(data: dict, status: int = 200) -> httpx.Response:  # type: ignore[type-arg]
    """Return an ``httpx.Response`` wrapping ``{"data": data}`` as JSON."""
    return httpx.Response(status, json={"data": data})
