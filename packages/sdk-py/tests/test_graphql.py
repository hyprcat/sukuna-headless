"""Tests for the GraphQL transport layer (``midsphere._graphql.GraphQLClient``)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from helpers import API_KEY, GRAPHQL_URL

from midsphere import Midsphere
from midsphere.errors import MidsphereApiError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client() -> Midsphere:
    return Midsphere(api_key=API_KEY)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_successful_query_returns_data(respx_mock: respx.MockRouter) -> None:
    """A happy-path query returns the ``data`` dict."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"health": "ok"}})
    )

    async with _client() as c:
        data = await c.gql.request("{ health }")

    assert data["health"] == "ok"


async def test_sends_bearer_auth_and_content_type(respx_mock: respx.MockRouter) -> None:
    """Every GraphQL request carries the API key as a Bearer token and correct content-type."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"health": "ok"}})
    )

    async with _client() as c:
        await c.gql.request("{ health }")

    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {API_KEY}"
    assert "application/json" in req.headers["content-type"]


async def test_non_2xx_raises_api_error_with_status(respx_mock: respx.MockRouter) -> None:
    """A 500 response raises ``MidsphereApiError`` with ``.status == 500``."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(500, json={"errors": [{"message": "boom"}]})
    )

    async with _client() as c:
        with pytest.raises(MidsphereApiError) as exc_info:
            await c.gql.request("{ health }")

    assert exc_info.value.status == 500


async def test_401_raises_api_error_with_status(respx_mock: respx.MockRouter) -> None:
    """A 401 response raises ``MidsphereApiError`` with ``.status == 401``."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "Unauthorized"}]})
    )

    async with _client() as c:
        with pytest.raises(MidsphereApiError) as exc_info:
            await c.gql.request("{ health }")

    assert exc_info.value.status == 401


async def test_top_level_graphql_errors_on_200_raises_api_error(
    respx_mock: respx.MockRouter,
) -> None:
    """Top-level ``errors`` on a 200 response raises ``MidsphereApiError``."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "Not authenticated"}]})
    )

    async with _client() as c:
        with pytest.raises(MidsphereApiError):
            await c.gql.request("{ health }")


async def test_data_null_raises_api_error(respx_mock: respx.MockRouter) -> None:
    """``data: null`` in a 200 response raises ``MidsphereApiError`` (empty response)."""
    respx_mock.post(GRAPHQL_URL).mock(return_value=httpx.Response(200, json={"data": None}))

    async with _client() as c:
        with pytest.raises(MidsphereApiError) as exc_info:
            await c.gql.request("{ health }")

    assert "empty" in str(exc_info.value).lower()


async def test_network_error_raises_api_error(respx_mock: respx.MockRouter) -> None:
    """A network-level failure raises ``MidsphereApiError``."""
    respx_mock.post(GRAPHQL_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    async with _client() as c:
        with pytest.raises(MidsphereApiError):
            await c.gql.request("{ health }")


async def test_request_body_contains_query_and_variables(respx_mock: respx.MockRouter) -> None:
    """The outgoing request body encodes ``query`` and ``variables``."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"agent": None}})
    )

    async with _client() as c:
        await c.gql.request("query Agent($id: ID!) { agent(id: $id) { id } }", {"id": "A:1"})

    body = json.loads(route.calls.last.request.content)
    assert "query" in body
    assert body["variables"] == {"id": "A:1"}
