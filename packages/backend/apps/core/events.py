from __future__ import annotations

from typing import Any

import posthog
import structlog

_log = structlog.get_logger(__name__)


def record_event(
    name: str,
    *,
    distinct_id: str,
    properties: dict[str, Any] | None = None,
    groups: dict[str, str] | None = None,
) -> None:
    """Emit a domain event to PostHog and structured logs."""
    props = properties or {}
    _log.info(name, distinct_id=distinct_id, **props)
    _capture_posthog(name, distinct_id=distinct_id, properties=props, groups=groups)


def _capture_posthog(
    name: str,
    *,
    distinct_id: str,
    properties: dict[str, Any],
    groups: dict[str, str] | None,
) -> None:
    if posthog.disabled or not posthog.api_key:
        return
    try:
        posthog.capture(
            distinct_id=distinct_id,
            event=name,
            properties=properties,
            groups=groups,
        )
    except Exception as exc:
        _log.warning("posthog_capture_failed", event_name=name, error=str(exc))


def identify_end_user(
    distinct_id: str,
    *,
    properties: dict[str, Any] | None = None,
) -> None:
    """Attach person properties in PostHog. Safe when PostHog is disabled.

    PostHog Python v3 replaced ``identify`` with ``set`` for attaching person
    properties (no separate "identify" call exists; events themselves create
    the person row, and ``set`` updates its properties).
    """
    if posthog.disabled or not posthog.api_key:
        return
    try:
        posthog.set(distinct_id=distinct_id, properties=properties or {})
    except Exception as exc:
        _log.warning("posthog_set_failed", distinct_id=distinct_id, error=str(exc))
