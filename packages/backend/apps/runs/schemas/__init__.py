"""Pydantic v2 schemas for the run / sandbox boundary.

These types are the contract the Django backend speaks with `agent_server`
inside the E2B sandbox. They live in `schemas/` (not `models/`) because they
are pure data — no Django, no ORM, no I/O — so they can be imported at
import-time anywhere without dragging the app registry along.

The sandbox's *internal* layout is being refactored; the *data contract*
captured here is stable. Keep these types in lockstep with the runtime's
documented wire shapes rather than its private folder layout.
"""

from __future__ import annotations

from apps.runs.schemas.errors import DomainErrorCode, LeaseErrorCode
from apps.runs.schemas.events import (
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    RunStatus,
    RunUsage,
    UsageEvent,
)
from apps.runs.schemas.lease import Lease, LeaseUsage
from apps.runs.schemas.request import RunRequest
from apps.runs.schemas.state import RunState

__all__ = [
    "DomainErrorCode",
    "Lease",
    "LeaseErrorCode",
    "LeaseUsage",
    "RunCancelled",
    "RunFailed",
    "RunFinished",
    "RunRequest",
    "RunStarted",
    "RunState",
    "RunStatus",
    "RunUsage",
    "UsageEvent",
]
