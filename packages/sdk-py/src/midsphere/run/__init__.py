"""
Public surface of the ``midsphere.run`` subpackage.

Re-exports the complete streaming/run API so callers can do::

    from midsphere.run import Run, RunOutcome, StreamEvent
"""

from __future__ import annotations

from midsphere.run.events import (
    KNOWN_EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    ArtifactCreatedPayload,
    HitlRequestedPayload,
    HitlRespondedPayload,
    LeaseUsageDict,
    RunCancelledPayload,
    RunCompletedPayload,
    RunFailedPayload,
    RunStartedPayload,
    StepPayload,
    StreamEvent,
    StreamEventType,
    ToolCallPayload,
    ToolResultPayload,
    UsageCheckpointPayload,
    is_terminal_type,
    parse_stream_event,
)
from midsphere.run.run import RefreshTokenFn, Run, RunOutcome
from midsphere.run.sandbox import SandboxConnection

__all__ = [
    # events
    "StreamEvent",
    "StreamEventType",
    "TERMINAL_EVENT_TYPES",
    "KNOWN_EVENT_TYPES",
    "is_terminal_type",
    "parse_stream_event",
    # payload TypedDicts
    "LeaseUsageDict",
    "RunStartedPayload",
    "StepPayload",
    "ToolCallPayload",
    "ToolResultPayload",
    "HitlRequestedPayload",
    "HitlRespondedPayload",
    "ArtifactCreatedPayload",
    "UsageCheckpointPayload",
    "RunCompletedPayload",
    "RunFailedPayload",
    "RunCancelledPayload",
    # run
    "Run",
    "RunOutcome",
    "RefreshTokenFn",
    # sandbox
    "SandboxConnection",
]
