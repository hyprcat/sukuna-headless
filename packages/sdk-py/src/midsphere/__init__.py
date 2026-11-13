"""
``midsphere`` — the official Python SDK for midsphere.

Run agents, stream their progress, and manage end users and ratings against
the same GraphQL surface the dashboard uses. See the README for a quick start.

Typical usage::

    from midsphere import Midsphere

    async with Midsphere(api_key="ms_prod_...") as client:
        run = await client.run(
            agent_id="QWdlbnRUeXBlOjE=",
            end_user_id="RW5kVXNlclR5cGU6MQ==",
            prompt="Summarize today's signups",
        )
        outcome = await run.wait()
"""

from __future__ import annotations

__version__ = "0.1.0"

# Client
from .client import AgentRef, Midsphere

# Errors
from .errors import MidsphereApiError, MidsphereError, MidsphereStreamError, MidsphereUserError

# Resources
from .resources import Agents, EndUsers, KnowledgeBases, Ratings, Tools

# Stream events
from .run.events import (
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

# Run lifecycle
from .run.run import RefreshTokenFn, Run, RunOutcome
from .run.sandbox import SandboxConnection

# Types
from .types import (
    Agent,
    EndUser,
    Knowledge,
    KnowledgeKind,
    KnowledgeKindInput,
    ModelTier,
    RunStatus,
    Tool,
    UserError,
    UserErrorCode,
)

__all__ = [
    "__version__",
    # Client
    "Midsphere",
    "AgentRef",
    # Run
    "Run",
    "RunOutcome",
    "RefreshTokenFn",
    "SandboxConnection",
    # Stream events
    "StreamEvent",
    "StreamEventType",
    "TERMINAL_EVENT_TYPES",
    "is_terminal_type",
    "parse_stream_event",
    # Payload TypedDicts
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
    # Resources
    "Agents",
    "Tools",
    "KnowledgeBases",
    "EndUsers",
    "Ratings",
    # Errors
    "MidsphereError",
    "MidsphereApiError",
    "MidsphereUserError",
    "MidsphereStreamError",
    # Types
    "Agent",
    "Tool",
    "Knowledge",
    "EndUser",
    "UserError",
    "ModelTier",
    "RunStatus",
    "KnowledgeKind",
    "KnowledgeKindInput",
    "UserErrorCode",
]
