"""
Low-level HTTP client bound to a single running sandbox.

Sandboxes are reached via the Caddy reverse proxy at
``https://{sandbox_id}.run.midsphere.com``. Auth is a short-lived capability
JWT sent as ``Authorization: Bearer <token>``. See :class:`~midsphere.run.run.Run`
for the higher-level lifecycle handle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import httpx
from httpx_sse import aconnect_sse

from midsphere.errors import MidsphereStreamError
from midsphere.run.events import StreamEvent, parse_stream_event

if TYPE_CHECKING:
    pass


class SandboxConnection:
    """Direct HTTP client bound to a single sandbox run."""

    def __init__(
        self,
        *,
        sandbox_url: str,
        run_uid: str,
        token: str,
        http: httpx.AsyncClient,
    ) -> None:
        self._base = sandbox_url.rstrip("/")
        self._run_uid = run_uid
        self._token = token
        self._http = http

    def set_token(self, token: str) -> None:
        """Update the capability token (called after a token refresh)."""
        self._token = token

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._token}"}

    # -------------------------------------------------------------------------
    # Methods
    # -------------------------------------------------------------------------

    async def stream(self, *, after: int | None = None) -> AsyncIterator[StreamEvent]:
        """Open the sandbox SSE stream for this run.

        Yields :class:`~midsphere.run.events.StreamEvent` objects in order and
        terminates naturally after the terminal event (``run_completed``,
        ``run_failed``, or ``run_cancelled``).

        Raises :class:`~midsphere.errors.MidsphereStreamError` on non-2xx
        responses or transport failures. Lets ``asyncio.CancelledError``
        propagate unchanged.
        """
        url = f"{self._base}/runs/{self._run_uid}/stream"
        params = {"after": str(after)} if after is not None else {}
        headers = {**self._headers(), "accept": "text/event-stream"}

        try:
            async with aconnect_sse(
                self._http,
                "GET",
                url,
                headers=headers,
                params=params,
            ) as event_source:
                status = event_source.response.status_code
                if status >= 400:
                    raise MidsphereStreamError(
                        f"Sandbox stream failed (HTTP {status}).",
                        status=status,
                    )

                async for sse in event_source.aiter_sse():
                    evt = parse_stream_event(sse.data)
                    if evt is None:
                        continue
                    yield evt
                    if evt.is_terminal:
                        return

        except MidsphereStreamError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise MidsphereStreamError(
                f"Sandbox stream failed (HTTP {status}).",
                status=status,
            ) from exc
        except Exception as exc:
            # Let asyncio.CancelledError (BaseException subclass) propagate.
            raise MidsphereStreamError(
                "Sandbox stream request failed.",
                cause=exc,
            ) from exc

    async def cancel(self) -> None:
        """Request cancellation of the run (``DELETE /runs/{run_uid}``).

        Raises :class:`~midsphere.errors.MidsphereStreamError` on non-2xx
        responses or transport failures.
        """
        url = f"{self._base}/runs/{self._run_uid}"
        try:
            response = await self._http.delete(url, headers=self._headers())
        except Exception as exc:
            raise MidsphereStreamError(
                "Sandbox cancel request failed.",
                cause=exc,
            ) from exc

        if response.status_code >= 400:
            status = response.status_code
            raise MidsphereStreamError(
                f"Sandbox cancel failed (HTTP {status}).",
                status=status,
            )

    async def respond_to_hitl(self, request_id: str, decision: str) -> None:
        """Submit a human-in-the-loop decision for ``request_id``.

        Sends ``POST /runs/{run_uid}/hitl/{request_id}`` with
        ``{"response": decision}``. Raises
        :class:`~midsphere.errors.MidsphereStreamError` on non-2xx responses
        or transport failures.
        """
        url = f"{self._base}/runs/{self._run_uid}/hitl/{request_id}"
        headers = {**self._headers(), "content-type": "application/json"}
        try:
            response = await self._http.post(
                url,
                headers=headers,
                json={"response": decision},
            )
        except Exception as exc:
            raise MidsphereStreamError(
                "Sandbox HITL request failed.",
                cause=exc,
            ) from exc

        if response.status_code >= 400:
            status = response.status_code
            raise MidsphereStreamError(
                f"Sandbox HITL response failed (HTTP {status}).",
                status=status,
            )
