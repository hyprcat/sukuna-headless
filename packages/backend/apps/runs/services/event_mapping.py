"""Event type → UsageEvent mapping for callback ingestion."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from apps.runs.schemas.errors import DomainErrorCode, LeaseErrorCode
from apps.runs.schemas.events import (
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    RunUsage,
    UsageEvent,
)

if TYPE_CHECKING:
    from uuid import UUID

EventMapper = Callable[[dict[str, Any], dict[str, Any]], UsageEvent]

_KNOWN_ERROR_CODES = {c.value for c in LeaseErrorCode} | {c.value for c in DomainErrorCode}


def _coerce_error_code(raw: Any) -> str | None:
    """Map an unrecognized sandbox error code to a known one.

    The sandbox may emit codes outside our closed taxonomy (e.g.
    ``internal_error``). Falling through to pydantic would 500 the callback and
    orphan the run, so anything unknown collapses to ``sandbox_internal``.
    """
    if raw is None:
        return None
    return raw if raw in _KNOWN_ERROR_CODES else DomainErrorCode.SANDBOX_INTERNAL.value


def map_to_usage_event(
    event_data: dict[str, Any],
    run_uid: UUID,
) -> UsageEvent | None:
    """Translate a raw callback event dict into a typed UsageEvent."""
    event_type = event_data.get("event_type", "")
    mapper = _EventMappers().dispatch.get(event_type)
    if mapper is None:
        return None
    payload = event_data.get("payload", {})
    base: dict[str, Any] = {
        "run_id": run_uid,
        "sequence_no": event_data.get("sequence_no", 0),
        "emitted_at": event_data.get("emitted_at"),
    }
    return mapper(base, payload)


def _map_started(base: dict[str, Any], payload: dict[str, Any]) -> RunStarted:
    return RunStarted(**base, sandbox_id=payload.get("sandbox_id"))


def _map_usage(base: dict[str, Any], payload: dict[str, Any]) -> RunUsage:
    return RunUsage(
        **base,
        total_tokens=payload.get("total_tokens", 0),
        cost_usd=Decimal(str(payload.get("cost_usd", "0"))),
    )


def _map_completed(base: dict[str, Any], payload: dict[str, Any]) -> RunFinished:
    fu = payload.get("final_usage", {})
    return RunFinished(
        **base,
        final_total_tokens=fu.get("total_tokens", 0),
        final_cost_usd=Decimal(str(fu.get("cost_usd", "0"))),
    )


def _map_failed(base: dict[str, Any], payload: dict[str, Any]) -> RunFailed:
    fu = payload.get("final_usage", {})
    return RunFailed(
        **base,
        error=payload.get("message", "Unknown error"),
        error_code=_coerce_error_code(payload.get("error_code")),
        final_cost_usd=Decimal(str(fu.get("cost_usd", "0"))),
    )


def _map_cancelled(base: dict[str, Any], payload: dict[str, Any]) -> RunCancelled:
    fu = payload.get("final_usage", {})
    return RunCancelled(
        **base,
        final_cost_usd=Decimal(str(fu.get("cost_usd", "0"))),
    )


class _EventMappers(BaseModel):
    model_config = ConfigDict(frozen=True)
    dispatch: dict[str, EventMapper] = Field(
        default_factory=lambda: {
            "run_started": _map_started,
            "usage_checkpoint": _map_usage,
            "run_completed": _map_completed,
            "run_failed": _map_failed,
            "run_cancelled": _map_cancelled,
        }
    )
