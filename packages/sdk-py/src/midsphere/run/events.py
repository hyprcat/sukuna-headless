"""
Sandbox streaming event contract.

The sandbox emits Server-Sent Events; each message's ``data`` field is a JSON
string with snake_case keys. Payload fields mirror the runtime wire contract
exactly — do not rename them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

LeaseUsage = dict  # {"runtime_seconds": int, "total_tokens": int, "cost_usd": str}

# ---------------------------------------------------------------------------
# Per-type payload TypedDicts (typing/export only; payloads at runtime are plain dicts)
# ---------------------------------------------------------------------------


class LeaseUsageDict(TypedDict):
    runtime_seconds: int
    total_tokens: int
    cost_usd: str  # stringified decimal, e.g. "0.0142"


class RunStartedPayload(TypedDict):
    model_tier: str
    sandbox_id: str


class StepPayload(TypedDict):
    step_index: int
    reasoning: str
    output: str


class ToolCallPayload(TypedDict):
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    is_mcp: bool


class ToolResultPayload(TypedDict, total=False):
    call_id: str
    tool_name: str
    result: Any  # str | dict
    error: str
    duration_ms: int


class HitlRequestedPayload(TypedDict):
    request_id: str
    prompt: str
    choices: list[str]


class HitlRespondedPayload(TypedDict):
    request_id: str
    response: str  # "approve" | "deny"
    responded_at: str


class ArtifactCreatedPayload(TypedDict):
    artifact_id: str
    name: str
    content_type: str
    size_bytes: int
    storage_ref: str


class UsageCheckpointPayload(TypedDict):
    runtime_seconds: int
    total_tokens: int
    cost_usd: str
    tool_calls_count: int


class RunCompletedPayload(TypedDict):
    final_usage: LeaseUsageDict
    summary: str


class RunFailedPayload(TypedDict):
    error_code: str
    message: str
    final_usage: LeaseUsageDict


class RunCancelledPayload(TypedDict):
    reason: str
    final_usage: LeaseUsageDict


# ---------------------------------------------------------------------------
# Discriminant literal type
# ---------------------------------------------------------------------------

StreamEventType = Literal[
    "run_started",
    "step",
    "tool_call",
    "tool_result",
    "hitl_requested",
    "hitl_responded",
    "artifact_created",
    "usage_checkpoint",
    "run_completed",
    "run_failed",
    "run_cancelled",
]

# ---------------------------------------------------------------------------
# Terminal-event constants
# ---------------------------------------------------------------------------

TERMINAL_EVENT_TYPES: tuple[str, ...] = (
    "run_completed",
    "run_failed",
    "run_cancelled",
)

KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "run_started",
        "step",
        "tool_call",
        "tool_result",
        "hitl_requested",
        "hitl_responded",
        "artifact_created",
        "usage_checkpoint",
        "run_completed",
        "run_failed",
        "run_cancelled",
    }
)

# ---------------------------------------------------------------------------
# StreamEvent dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StreamEvent:
    """A single typed event from the sandbox SSE stream."""

    event_id: str
    sequence_no: int
    type: str
    payload: dict[str, Any]
    emitted_at: str

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` when this event ends the run."""
        return self.type in TERMINAL_EVENT_TYPES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_terminal_type(t: str) -> bool:
    """Return ``True`` when ``t`` is one of the three terminal type strings."""
    return t in TERMINAL_EVENT_TYPES


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_stream_event(data: str) -> StreamEvent | None:
    """Parse the raw ``data`` string of an SSE message into a :class:`StreamEvent`.

    Returns ``None`` for:

    - empty or whitespace-only data
    - JSON parse errors
    - non-object JSON values
    - missing or non-string ``event_type``
    - unknown ``event_type`` (forward-compatible: new types are silently skipped)
    - non-integer ``sequence_no``
    - non-string ``event_id``
    - non-string ``emitted_at``

    Otherwise returns a :class:`StreamEvent`. ``payload`` defaults to ``{}``
    when absent from the envelope.
    """
    if not data or not data.strip():
        return None

    try:
        raw: Any = json.loads(data)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(raw, dict):
        return None

    event_type = raw.get("event_type")
    if not isinstance(event_type, str):
        return None
    if event_type not in KNOWN_EVENT_TYPES:
        return None

    sequence_no = raw.get("sequence_no")
    if not isinstance(sequence_no, int):
        return None

    event_id = raw.get("event_id")
    if not isinstance(event_id, str):
        return None

    emitted_at = raw.get("emitted_at")
    if not isinstance(emitted_at, str):
        return None

    payload: dict[str, Any] = raw.get("payload") or {}

    return StreamEvent(
        event_id=event_id,
        sequence_no=sequence_no,
        type=event_type,
        payload=payload,
        emitted_at=emitted_at,
    )
