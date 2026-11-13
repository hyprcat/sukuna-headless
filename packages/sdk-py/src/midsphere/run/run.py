"""
High-level handle to a started run.

Wraps a :class:`~midsphere.run.sandbox.SandboxConnection` and exposes a clean
lifecycle API: streaming events, waiting for the terminal outcome, cancelling,
responding to HITL prompts, and refreshing the short-lived capability token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from midsphere.errors import MidsphereStreamError
from midsphere.run.events import StreamEvent, is_terminal_type
from midsphere.run.sandbox import SandboxConnection

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

RefreshTokenFn = Callable[[], Awaitable[dict[str, Any]]]
"""Async callable that returns ``{"capability_token": str, "token_expires_at": str | None}``."""


@dataclass(slots=True)
class RunOutcome:
    """Outcome returned by :meth:`Run.wait` once the run has reached a terminal state."""

    status: str  # FINISHED | FAILED | CANCELLED
    last_event: StreamEvent
    summary: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    usage: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Run class
# ---------------------------------------------------------------------------


class Run:
    """A handle to a started agent run."""

    #: Relay global ID (control-plane identifier).
    id: str
    #: Internal UID used by the sandbox.
    uid: str
    #: URL base of the sandbox proxy.
    sandbox_url: str
    #: Current lifecycle status. Updated as events arrive.
    status: str

    def __init__(
        self,
        *,
        run_id: str,
        run_uid: str,
        sandbox_url: str,
        capability_token: str,
        token_expires_at: str | None,
        http: httpx.AsyncClient,
        refresh: RefreshTokenFn | None = None,
    ) -> None:
        self.id = run_id
        self.uid = run_uid
        self.sandbox_url = sandbox_url
        self.status = "QUEUED"
        self._raw_token_expires_at = token_expires_at
        self._refresh = refresh
        self._connection = SandboxConnection(
            sandbox_url=sandbox_url,
            run_uid=run_uid,
            token=capability_token,
            http=http,
        )

    @property
    def token_expires_at(self) -> datetime | None:
        """Expiry of the current capability token, or ``None`` if unknown."""
        if self._raw_token_expires_at is None:
            return None
        raw = self._raw_token_expires_at
        # datetime.fromisoformat does not handle trailing Z before Python 3.11.
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)

    @property
    def debug_console_url(self) -> str | None:
        """URL of the agent's in-sandbox debug console (an Astro UI on port 4321).

        Derived from the sandbox proxy host by swapping the agent-server port
        segment (``8000``) for the console port (``4321``) — e.g.
        ``https://8000-<id>.e2b.app`` becomes ``https://4321-<id>.e2b.app``.
        Returns ``None`` when the sandbox URL isn't in that ``<port>-<id>`` host
        form (e.g. behind a production wildcard proxy that hides the port).
        """
        from urllib.parse import urlsplit, urlunsplit

        agent_port, console_port = "8000-", "4321-"
        parts = urlsplit(self.sandbox_url)
        if not parts.netloc.startswith(agent_port):
            return None
        console_host = console_port + parts.netloc[len(agent_port) :]
        return urlunsplit((parts.scheme, console_host, "", "", ""))

    # -------------------------------------------------------------------------
    # Streaming
    # -------------------------------------------------------------------------

    async def stream(self, *, after: int | None = None) -> AsyncIterator[StreamEvent]:
        """Stream sandbox events for this run.

        Sets ``status`` to ``'RUNNING'`` on the first event and updates it to
        the appropriate terminal value on the last. The terminal event is
        yielded before the generator returns.
        """
        started = False
        async for event in self._connection.stream(after=after):
            if not started:
                started = True
                self.status = "RUNNING"

            if is_terminal_type(event.type):
                self.status = _terminal_status(event.type)
                yield event
                return

            yield event

    # -------------------------------------------------------------------------
    # Wait for outcome
    # -------------------------------------------------------------------------

    async def wait(self) -> RunOutcome:
        """Consume the stream and return a structured :class:`RunOutcome`.

        Raises :class:`~midsphere.errors.MidsphereStreamError` when the stream
        ends without a terminal event.
        """
        last: StreamEvent | None = None
        async for event in self.stream():
            last = event

        if last is None or not is_terminal_type(last.type):
            raise MidsphereStreamError("Run stream ended before a terminal event.")

        return _build_outcome(last)

    # -------------------------------------------------------------------------
    # Control operations
    # -------------------------------------------------------------------------

    async def cancel(self) -> None:
        """Request cancellation of the run.

        Optimistically sets ``status`` to ``'CANCELLED'`` before the sandbox
        acknowledges.
        """
        await self._connection.cancel()
        self.status = "CANCELLED"

    async def respond(self, request_id: str, decision: str) -> None:
        """Submit a human-in-the-loop decision."""
        await self._connection.respond_to_hitl(request_id, decision)

    async def refresh_token(self) -> None:
        """Refresh the capability token using the client-supplied :data:`RefreshTokenFn`.

        Raises :class:`~midsphere.errors.MidsphereStreamError` when no refresh
        function was provided.
        """
        if self._refresh is None:
            raise MidsphereStreamError("This run cannot refresh its token (no client context).")
        result = await self._refresh()
        self._connection.set_token(result["capability_token"])
        self._raw_token_expires_at = result.get("token_expires_at")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _terminal_status(event_type: str) -> str:
    if event_type == "run_completed":
        return "FINISHED"
    if event_type == "run_failed":
        return "FAILED"
    return "CANCELLED"


def _build_outcome(event: StreamEvent) -> RunOutcome:
    p = event.payload
    if event.type == "run_completed":
        return RunOutcome(
            status="FINISHED",
            last_event=event,
            summary=p.get("summary"),
            usage=p.get("final_usage"),
        )
    if event.type == "run_failed":
        return RunOutcome(
            status="FAILED",
            last_event=event,
            error_code=p.get("error_code"),
            error_message=p.get("message"),
            usage=p.get("final_usage"),
        )
    if event.type == "run_cancelled":
        return RunOutcome(
            status="CANCELLED",
            last_event=event,
            usage=p.get("final_usage"),
        )
    # Guard: _build_outcome is only ever called with a terminal event.
    raise MidsphereStreamError(f'Expected a terminal event, got "{event.type}".')
