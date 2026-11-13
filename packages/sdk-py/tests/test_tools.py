"""Tests for the Tools resource."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from helpers import API_KEY, GRAPHQL_URL

from midsphere import Midsphere
from midsphere.errors import MidsphereUserError


def _client() -> Midsphere:
    return Midsphere(api_key=API_KEY)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# camelCase node as the backend returns it.
_FAKE_TOOL_NODE = {
    "id": "T:1",
    "name": "web_search",
    "description": "Search the web and return results.",
    "parametersSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    "executionEndpoint": "https://tools.example.com/web_search",
    "isSensitive": False,
    "isActive": True,
    "createdAt": "2026-06-21T00:00:00Z",
    "updatedAt": "2026-06-21T00:00:00Z",
    "deactivatedAt": None,
}


# ---------------------------------------------------------------------------
# tools.list
# ---------------------------------------------------------------------------


async def test_tools_list_returns_mapped_nodes(respx_mock: respx.MockRouter) -> None:
    """``tools.list`` maps edges to Tool dataclasses."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"tools": {"edges": [{"node": _FAKE_TOOL_NODE}]}}}
        )
    )

    async with _client() as c:
        tools = await c.tools.list()

    assert len(tools) == 1
    t = tools[0]
    assert t.id == "T:1"
    assert t.name == "web_search"
    assert t.is_sensitive is False
    assert t.is_active is True
    assert t.deactivated_at is None


async def test_tools_list_sends_is_active_and_first(respx_mock: respx.MockRouter) -> None:
    """``tools.list`` passes ``isActive`` and ``first`` as GraphQL variables."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"tools": {"edges": []}}})
    )

    async with _client() as c:
        await c.tools.list(is_active=True, first=10)

    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"isActive": True, "first": 10}


async def test_tools_list_defaults_is_active_null_first_50(respx_mock: respx.MockRouter) -> None:
    """``tools.list`` defaults ``isActive=None`` and ``first=50``."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"tools": {"edges": []}}})
    )

    async with _client() as c:
        await c.tools.list()

    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"isActive": None, "first": 50}


# ---------------------------------------------------------------------------
# tools.get
# ---------------------------------------------------------------------------


async def test_tools_get_returns_tool_when_found(respx_mock: respx.MockRouter) -> None:
    """``tools.get`` returns the Tool when the backend returns a node."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"tool": _FAKE_TOOL_NODE}})
    )

    async with _client() as c:
        tool = await c.tools.get("T:1")

    assert tool is not None
    assert tool.id == "T:1"


async def test_tools_get_returns_none_when_not_found(respx_mock: respx.MockRouter) -> None:
    """``tools.get`` returns ``None`` when the backend returns null."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"tool": None}})
    )

    async with _client() as c:
        tool = await c.tools.get("nonexistent")

    assert tool is None


# ---------------------------------------------------------------------------
# tools.create
# ---------------------------------------------------------------------------


async def test_tools_create_returns_projected_tool(respx_mock: respx.MockRouter) -> None:
    """``tools.create`` returns the newly created Tool on success."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"createTool": {"success": True, "errors": [], "tool": _FAKE_TOOL_NODE}}},
        )
    )

    async with _client() as c:
        tool = await c.tools.create(
            name="web_search",
            execution_endpoint="https://tools.example.com/web_search",
        )

    assert tool.id == "T:1"
    assert tool.name == "web_search"


async def test_tools_create_sends_only_provided_keys(respx_mock: respx.MockRouter) -> None:
    """Only the provided kwargs are sent in ``variables.input``; omitted ones are absent."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"createTool": {"success": True, "errors": [], "tool": _FAKE_TOOL_NODE}}},
        )
    )

    async with _client() as c:
        await c.tools.create(
            name="web_search",
            execution_endpoint="https://tools.example.com/web_search",
        )

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["input"] == {
        "name": "web_search",
        "executionEndpoint": "https://tools.example.com/web_search",
    }


async def test_tools_create_includes_all_optional_fields(respx_mock: respx.MockRouter) -> None:
    """When all optional fields are provided they appear in ``variables.input``."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"createTool": {"success": True, "errors": [], "tool": _FAKE_TOOL_NODE}}},
        )
    )

    async with _client() as c:
        await c.tools.create(
            name="web_search",
            description="Search the web.",
            parameters_schema={"type": "object"},
            execution_endpoint="https://tools.example.com/web_search",
            is_sensitive=False,
        )

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["input"] == {
        "name": "web_search",
        "description": "Search the web.",
        "parametersSchema": {"type": "object"},
        "executionEndpoint": "https://tools.example.com/web_search",
        "isSensitive": False,
    }


async def test_tools_create_domain_failure_raises_user_error(
    respx_mock: respx.MockRouter,
) -> None:
    """A domain failure (``success=false``) raises ``MidsphereUserError``."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createTool": {
                        "success": False,
                        "errors": [
                            {
                                "code": "INVALID_INPUT",
                                "field": "name",
                                "message": "Name is required.",
                            }
                        ],
                        "tool": None,
                    }
                }
            },
        )
    )

    async with _client() as c:
        with pytest.raises(MidsphereUserError):
            await c.tools.create(name="")


async def test_tools_create_exposes_error_code(respx_mock: respx.MockRouter) -> None:
    """The ``MidsphereUserError`` raised carries the domain error code."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createTool": {
                        "success": False,
                        "errors": [
                            {
                                "code": "CONFLICT",
                                "field": "name",
                                "message": "A tool with this name already exists.",
                            }
                        ],
                        "tool": None,
                    }
                }
            },
        )
    )

    async with _client() as c:
        with pytest.raises(MidsphereUserError) as exc_info:
            await c.tools.create(name="web_search")

    assert exc_info.value.code == "CONFLICT"


# ---------------------------------------------------------------------------
# tools.update
# ---------------------------------------------------------------------------


async def test_tools_update_returns_updated_tool(respx_mock: respx.MockRouter) -> None:
    """``tools.update`` returns the updated Tool."""
    updated_node = {**_FAKE_TOOL_NODE, "name": "web_search_v2"}
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"updateTool": {"success": True, "errors": [], "tool": updated_node}}},
        )
    )

    async with _client() as c:
        tool = await c.tools.update("T:1", name="web_search_v2")

    assert tool.name == "web_search_v2"


async def test_tools_update_sends_only_provided_keys_plus_id(
    respx_mock: respx.MockRouter,
) -> None:
    """``variables.id`` carries the tool ID and ``variables.input`` only the changed field."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"updateTool": {"success": True, "errors": [], "tool": _FAKE_TOOL_NODE}}},
        )
    )

    async with _client() as c:
        await c.tools.update("T:1", description="Updated description.")

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["id"] == "T:1"
    assert body["variables"]["input"] == {"description": "Updated description."}


async def test_tools_update_omits_unprovided_fields(respx_mock: respx.MockRouter) -> None:
    """Omitted kwargs do not appear in ``variables.input``."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"updateTool": {"success": True, "errors": [], "tool": _FAKE_TOOL_NODE}}},
        )
    )

    async with _client() as c:
        await c.tools.update("T:1", is_sensitive=True)

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["input"] == {"isSensitive": True}
    assert "name" not in body["variables"]["input"]
    assert "description" not in body["variables"]["input"]


# ---------------------------------------------------------------------------
# tools.activate
# ---------------------------------------------------------------------------


async def test_tools_activate_sends_id_and_returns_tool(respx_mock: respx.MockRouter) -> None:
    """``tools.activate`` sends only the ``id`` variable and returns the active Tool."""
    active_node = {**_FAKE_TOOL_NODE, "isActive": True, "deactivatedAt": None}
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"activateTool": {"success": True, "errors": [], "tool": active_node}}},
        )
    )

    async with _client() as c:
        tool = await c.tools.activate("T:1")

    assert tool.is_active is True
    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"id": "T:1"}


# ---------------------------------------------------------------------------
# tools.deactivate
# ---------------------------------------------------------------------------


async def test_tools_deactivate_sends_id_and_returns_tool(respx_mock: respx.MockRouter) -> None:
    """``tools.deactivate`` sends only the ``id`` variable and returns the deactivated Tool."""
    inactive_node = {
        **_FAKE_TOOL_NODE,
        "isActive": False,
        "deactivatedAt": "2026-06-21T12:00:00Z",
    }
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"deactivateTool": {"success": True, "errors": [], "tool": inactive_node}}
            },
        )
    )

    async with _client() as c:
        tool = await c.tools.deactivate("T:1")

    assert tool.is_active is False
    assert tool.deactivated_at == "2026-06-21T12:00:00Z"
    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"id": "T:1"}
