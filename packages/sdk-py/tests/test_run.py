"""Integration tests for ``Midsphere.run`` and the ``Run`` lifecycle.

Ports ``sdk-ts/test/run.test.ts`` to Python.  All HTTP is intercepted by
``respx_mock`` so no real network calls are made.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from helpers import (
    API_KEY,
    GRAPHQL_URL,
    RUN_ID,
    RUN_UID,
    SANDBOX_URL,
    graphql_response,
    happy_path_events,
    sse_response,
)

from midsphere import Midsphere
from midsphere.errors import MidsphereStreamError, MidsphereUserError
from midsphere.run.run import Run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _start_run_ok_data() -> dict:  # type: ignore[type-arg]
    return {
        "startRun": {
            "success": True,
            "errors": [],
            "runId": RUN_ID,
            "runUid": RUN_UID,
            "sandboxUrl": SANDBOX_URL,
            "capabilityToken": "cap-token",
            "tokenExpiresAt": "2026-06-21T01:00:00Z",
        }
    }


def _mock_start_run(respx_mock: respx.MockRouter) -> respx.Route:
    """Register a successful startRun POST on the GraphQL URL."""
    return respx_mock.post(GRAPHQL_URL).mock(return_value=graphql_response(_start_run_ok_data()))


def _stream_url() -> str:
    return f"{SANDBOX_URL}/runs/{RUN_UID}/stream"


def _mock_stream(
    respx_mock: respx.MockRouter,
    events: list[dict] | None = None,  # type: ignore[type-arg]
) -> respx.Route:
    """Register a sandbox SSE stream GET route."""
    return respx_mock.get(_stream_url()).mock(
        return_value=sse_response(events if events is not None else happy_path_events())
    )


# ---------------------------------------------------------------------------
# start: identifiers and metadata
# ---------------------------------------------------------------------------


async def test_run_exposes_identifiers(respx_mock: respx.MockRouter) -> None:
    """``client.run()`` returns a Run with correct uid, id, sandbox_url."""
    _mock_start_run(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")

    assert run.uid == RUN_UID
    assert run.id == RUN_ID
    assert run.sandbox_url == SANDBOX_URL


async def test_run_token_expires_at_parses_correctly(respx_mock: respx.MockRouter) -> None:
    """``token_expires_at`` is a timezone-aware UTC datetime."""
    _mock_start_run(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")

    ts = run.token_expires_at
    assert ts is not None
    assert ts.tzinfo is not None
    assert ts.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert ts.replace(tzinfo=None).isoformat() == "2026-06-21T01:00:00"


# ---------------------------------------------------------------------------
# start: domain failure
# ---------------------------------------------------------------------------


async def test_start_run_domain_failure_raises_user_error(respx_mock: respx.MockRouter) -> None:
    """A ``success=False`` startRun response raises ``MidsphereUserError``."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=graphql_response(
            {
                "startRun": {
                    "success": False,
                    "errors": [
                        {
                            "code": "INSUFFICIENT_CREDITS",
                            "field": None,
                            "message": "No credits left",
                        }
                    ],
                    "runId": None,
                    "runUid": None,
                    "sandboxUrl": None,
                    "capabilityToken": None,
                    "tokenExpiresAt": None,
                }
            }
        )
    )

    with pytest.raises(MidsphereUserError) as exc_info:
        async with Midsphere(api_key=API_KEY) as c:
            await c.run(agent_id="a1", end_user_id="u1", prompt="hi")

    assert exc_info.value.code == "INSUFFICIENT_CREDITS"


# ---------------------------------------------------------------------------
# stream(): event order + status + auth header
# ---------------------------------------------------------------------------


async def test_stream_yields_events_in_order(respx_mock: respx.MockRouter) -> None:
    """``run.stream()`` yields all 5 happy-path events in sequence order."""
    _mock_start_run(respx_mock)
    _mock_stream(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        collected = [e async for e in run.stream()]

    assert [e.type for e in collected] == [
        "run_started",
        "tool_call",
        "tool_result",
        "usage_checkpoint",
        "run_completed",
    ]


async def test_stream_sets_status_finished(respx_mock: respx.MockRouter) -> None:
    """After streaming, ``run.status`` is ``'FINISHED'``."""
    _mock_start_run(respx_mock)
    _mock_stream(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        async for _ in run.stream():
            pass

    assert run.status == "FINISHED"


async def test_stream_sends_capability_token(respx_mock: respx.MockRouter) -> None:
    """The sandbox stream request carries ``Authorization: Bearer cap-token``."""
    _mock_start_run(respx_mock)
    stream_route = _mock_stream(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        async for _ in run.stream():
            pass

    req = stream_route.calls.last.request
    assert req.headers["authorization"] == "Bearer cap-token"


async def test_stream_hits_correct_sandbox_url(respx_mock: respx.MockRouter) -> None:
    """The GET URL is ``{SANDBOX_URL}/runs/{RUN_UID}/stream``."""
    _mock_start_run(respx_mock)
    stream_route = _mock_stream(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        async for _ in run.stream():
            pass

    req = stream_route.calls.last.request
    assert str(req.url) == _stream_url()


# ---------------------------------------------------------------------------
# wait(): RunOutcome
# ---------------------------------------------------------------------------


async def test_wait_returns_finished_outcome(respx_mock: respx.MockRouter) -> None:
    """``run.wait()`` resolves to a ``RunOutcome`` with status FINISHED."""
    _mock_start_run(respx_mock)
    _mock_stream(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        outcome = await run.wait()

    assert outcome.status == "FINISHED"


async def test_wait_extracts_summary(respx_mock: respx.MockRouter) -> None:
    """``outcome.summary`` matches the ``run_completed`` payload."""
    _mock_start_run(respx_mock)
    _mock_stream(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        outcome = await run.wait()

    assert outcome.summary == "done"


async def test_wait_extracts_usage(respx_mock: respx.MockRouter) -> None:
    """``outcome.usage`` carries the final usage from the terminal payload."""
    _mock_start_run(respx_mock)
    _mock_stream(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        outcome = await run.wait()

    assert outcome.usage is not None
    assert outcome.usage["total_tokens"] == 100


async def test_wait_last_event_is_terminal(respx_mock: respx.MockRouter) -> None:
    """``outcome.last_event.type`` is ``'run_completed'``."""
    _mock_start_run(respx_mock)
    _mock_stream(respx_mock)

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        outcome = await run.wait()

    assert outcome.last_event.type == "run_completed"


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------


async def test_cancel_issues_delete_to_sandbox(respx_mock: respx.MockRouter) -> None:
    """``run.cancel()`` sends ``DELETE {SANDBOX_URL}/runs/{RUN_UID}``."""
    _mock_start_run(respx_mock)
    cancel_route = respx_mock.delete(f"{SANDBOX_URL}/runs/{RUN_UID}").mock(
        return_value=httpx.Response(200)
    )

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        await run.cancel()

    assert cancel_route.called


async def test_cancel_sets_status_cancelled(respx_mock: respx.MockRouter) -> None:
    """After cancel, ``run.status`` is ``'CANCELLED'``."""
    _mock_start_run(respx_mock)
    respx_mock.delete(f"{SANDBOX_URL}/runs/{RUN_UID}").mock(return_value=httpx.Response(200))

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        await run.cancel()

    assert run.status == "CANCELLED"


# ---------------------------------------------------------------------------
# respond()
# ---------------------------------------------------------------------------


async def test_respond_posts_to_hitl_endpoint(respx_mock: respx.MockRouter) -> None:
    """``run.respond()`` POSTs to ``{SANDBOX_URL}/runs/{RUN_UID}/hitl/{request_id}``."""
    _mock_start_run(respx_mock)
    hitl_route = respx_mock.post(f"{SANDBOX_URL}/runs/{RUN_UID}/hitl/req1").mock(
        return_value=httpx.Response(200)
    )

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        await run.respond("req1", "approve")

    assert hitl_route.called


async def test_respond_body_contains_decision(respx_mock: respx.MockRouter) -> None:
    """The HITL POST body is ``{"response": "<decision>"}``."""
    _mock_start_run(respx_mock)
    hitl_route = respx_mock.post(f"{SANDBOX_URL}/runs/{RUN_UID}/hitl/req1").mock(
        return_value=httpx.Response(200)
    )

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        await run.respond("req1", "approve")

    body = json.loads(hitl_route.calls.last.request.content)
    assert body == {"response": "approve"}


# ---------------------------------------------------------------------------
# refresh_token()
# ---------------------------------------------------------------------------


async def test_refresh_token_updates_token(respx_mock: respx.MockRouter) -> None:
    """``run.refresh_token()`` calls the GraphQL mutation and updates the stored expiry."""
    respx_mock.post(GRAPHQL_URL).mock(
        side_effect=[
            graphql_response(_start_run_ok_data()),
            graphql_response(
                {
                    "refreshSandboxToken": {
                        "success": True,
                        "errors": [],
                        "capabilityToken": "new-cap-token",
                        "tokenExpiresAt": "2026-06-21T02:00:00Z",
                    }
                }
            ),
        ]
    )

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        await run.refresh_token()

    # No exception = success; new expiry is 02:00 UTC.
    ts = run.token_expires_at
    assert ts is not None
    assert ts.replace(tzinfo=None).isoformat() == "2026-06-21T02:00:00"


async def test_refresh_token_without_refresh_fn_raises_stream_error() -> None:
    """A ``Run`` built without a refresh fn raises ``MidsphereStreamError``."""
    run = Run(
        run_id=RUN_ID,
        run_uid=RUN_UID,
        sandbox_url=SANDBOX_URL,
        capability_token="tok",
        token_expires_at=None,
        http=httpx.AsyncClient(),
        refresh=None,
    )

    with pytest.raises(MidsphereStreamError):
        await run.refresh_token()


# ---------------------------------------------------------------------------
# refresh_token() with two sequential GraphQL calls
# ---------------------------------------------------------------------------


async def test_refresh_token_uses_post_graphql_call(respx_mock: respx.MockRouter) -> None:
    """The refresh mutation is a POST to GRAPHQL_URL (same endpoint)."""
    start_route = respx_mock.post(GRAPHQL_URL).mock(
        side_effect=[
            graphql_response(_start_run_ok_data()),
            graphql_response(
                {
                    "refreshSandboxToken": {
                        "success": True,
                        "errors": [],
                        "capabilityToken": "refreshed-token",
                        "tokenExpiresAt": None,
                    }
                }
            ),
        ]
    )

    async with Midsphere(api_key=API_KEY) as c:
        run = await c.run(agent_id="a1", end_user_id="u1", prompt="hi")
        await run.refresh_token()

    assert start_route.call_count == 2
