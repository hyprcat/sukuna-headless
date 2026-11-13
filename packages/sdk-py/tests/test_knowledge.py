"""Tests for the KnowledgeBases resource."""

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
_BASE_KNOWLEDGE_NODE = {
    "id": "KB:1",
    "name": "Product Docs",
    "description": "Official product documentation",
    "kind": "DOCUMENT",
    "fileName": "docs.pdf",
    "fileSizeBytes": 204800,
    "contentType": "application/pdf",
    "sourceEndpoint": "",
    "isActive": True,
    "createdAt": "2026-01-01T00:00:00Z",
    "updatedAt": "2026-01-02T00:00:00Z",
    "lastIndexedAt": "2026-01-02T01:00:00Z",
    "deactivatedAt": None,
}


# ---------------------------------------------------------------------------
# knowledge.list
# ---------------------------------------------------------------------------


async def test_knowledge_list_returns_mapped_nodes(respx_mock: respx.MockRouter) -> None:
    """``knowledge.list`` maps edges to Knowledge dataclasses."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"knowledgeBases": {"edges": [{"node": _BASE_KNOWLEDGE_NODE}]}}},
        )
    )

    async with _client() as c:
        result = await c.knowledge.list()

    assert len(result) == 1
    kb = result[0]
    assert kb.id == "KB:1"
    assert kb.kind == "DOCUMENT"


async def test_knowledge_list_sends_kind_is_active_first(respx_mock: respx.MockRouter) -> None:
    """``knowledge.list`` passes kind, isActive, and first as GraphQL variables."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"knowledgeBases": {"edges": [{"node": _BASE_KNOWLEDGE_NODE}]}}},
        )
    )

    async with _client() as c:
        await c.knowledge.list(kind="document", is_active=True, first=10)

    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"kind": "document", "isActive": True, "first": 10}


async def test_knowledge_list_sends_null_defaults(respx_mock: respx.MockRouter) -> None:
    """``knowledge.list`` sends null defaults when no filters are provided."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"knowledgeBases": {"edges": []}}},
        )
    )

    async with _client() as c:
        await c.knowledge.list()

    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"kind": None, "isActive": None, "first": 50}


# ---------------------------------------------------------------------------
# knowledge.get
# ---------------------------------------------------------------------------


async def test_knowledge_get_returns_knowledge(respx_mock: respx.MockRouter) -> None:
    """``knowledge.get`` returns the Knowledge when found."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"knowledgeBase": _BASE_KNOWLEDGE_NODE}})
    )

    async with _client() as c:
        kb = await c.knowledge.get("KB:1")

    assert kb is not None
    assert kb.name == "Product Docs"

    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"id": "KB:1"}


async def test_knowledge_get_returns_none_when_not_found(respx_mock: respx.MockRouter) -> None:
    """``knowledge.get`` returns ``None`` when the backend returns null."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"knowledgeBase": None}})
    )

    async with _client() as c:
        kb = await c.knowledge.get("KB:missing")

    assert kb is None


# ---------------------------------------------------------------------------
# knowledge.create
# ---------------------------------------------------------------------------


async def test_knowledge_create_returns_projected_knowledge(
    respx_mock: respx.MockRouter,
) -> None:
    """``knowledge.create`` returns the newly created Knowledge."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createKnowledge": {
                        "success": True,
                        "errors": [],
                        "knowledge": _BASE_KNOWLEDGE_NODE,
                    }
                }
            },
        )
    )

    async with _client() as c:
        kb = await c.knowledge.create(name="Product Docs", kind="document")

    assert kb.id == "KB:1"
    assert kb.kind == "DOCUMENT"


async def test_knowledge_create_sends_only_required_keys(respx_mock: respx.MockRouter) -> None:
    """When only required args are supplied, no optional keys leak into the input."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createKnowledge": {
                        "success": True,
                        "errors": [],
                        "knowledge": _BASE_KNOWLEDGE_NODE,
                    }
                }
            },
        )
    )

    async with _client() as c:
        await c.knowledge.create(name="Product Docs", kind="document")

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["input"] == {"name": "Product Docs", "kind": "document"}


async def test_knowledge_create_includes_optional_fields(respx_mock: respx.MockRouter) -> None:
    """Optional fields appear in the input when provided."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createKnowledge": {
                        "success": True,
                        "errors": [],
                        "knowledge": {
                            **_BASE_KNOWLEDGE_NODE,
                            "description": "A great doc",
                            "sourceEndpoint": "https://example.com",
                        },
                    }
                }
            },
        )
    )

    async with _client() as c:
        await c.knowledge.create(
            name="Product Docs",
            kind="document",
            description="A great doc",
            source_endpoint="https://example.com",
            source_config={"token": "abc"},
        )

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["input"] == {
        "name": "Product Docs",
        "kind": "document",
        "description": "A great doc",
        "sourceEndpoint": "https://example.com",
        "sourceConfig": {"token": "abc"},
    }


async def test_knowledge_create_domain_failure_raises_user_error(
    respx_mock: respx.MockRouter,
) -> None:
    """A domain failure raises ``MidsphereUserError``."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createKnowledge": {
                        "success": False,
                        "errors": [
                            {
                                "code": "INVALID_INPUT",
                                "field": "kind",
                                "message": "Invalid kind value",
                            }
                        ],
                        "knowledge": None,
                    }
                }
            },
        )
    )

    async with _client() as c:
        with pytest.raises(MidsphereUserError):
            await c.knowledge.create(name="Bad KB", kind="document")


# ---------------------------------------------------------------------------
# knowledge.update
# ---------------------------------------------------------------------------


async def test_knowledge_update_sends_only_provided_keys_plus_id(
    respx_mock: respx.MockRouter,
) -> None:
    """``knowledge.update`` sends only the provided keys plus the ``id`` variable."""
    updated_node = {
        **_BASE_KNOWLEDGE_NODE,
        "name": "Renamed Docs",
        "updatedAt": "2026-02-01T00:00:00Z",
    }
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "updateKnowledge": {
                        "success": True,
                        "errors": [],
                        "knowledge": updated_node,
                    }
                }
            },
        )
    )

    async with _client() as c:
        kb = await c.knowledge.update("KB:1", name="Renamed Docs")

    assert kb.name == "Renamed Docs"

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["id"] == "KB:1"
    assert body["variables"]["input"] == {"name": "Renamed Docs"}


# ---------------------------------------------------------------------------
# knowledge.activate
# ---------------------------------------------------------------------------


async def test_knowledge_activate_returns_updated_knowledge(
    respx_mock: respx.MockRouter,
) -> None:
    """``knowledge.activate`` returns the updated Knowledge and sends only ``id``."""
    activated_node = {**_BASE_KNOWLEDGE_NODE, "isActive": True, "deactivatedAt": None}
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "activateKnowledge": {
                        "success": True,
                        "errors": [],
                        "knowledge": activated_node,
                    }
                }
            },
        )
    )

    async with _client() as c:
        kb = await c.knowledge.activate("KB:1")

    assert kb.is_active is True

    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"id": "KB:1"}


# ---------------------------------------------------------------------------
# knowledge.deactivate
# ---------------------------------------------------------------------------


async def test_knowledge_deactivate_returns_updated_knowledge(
    respx_mock: respx.MockRouter,
) -> None:
    """``knowledge.deactivate`` returns the deactivated Knowledge with ``deactivated_at`` set."""
    deactivated_node = {
        **_BASE_KNOWLEDGE_NODE,
        "isActive": False,
        "deactivatedAt": "2026-06-21T00:00:00Z",
    }
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "deactivateKnowledge": {
                        "success": True,
                        "errors": [],
                        "knowledge": deactivated_node,
                    }
                }
            },
        )
    )

    async with _client() as c:
        kb = await c.knowledge.deactivate("KB:1")

    assert kb.is_active is False
    assert kb.deactivated_at == "2026-06-21T00:00:00Z"

    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"id": "KB:1"}


# ---------------------------------------------------------------------------
# knowledge.reindex
# ---------------------------------------------------------------------------


async def test_knowledge_reindex_sends_id_and_returns_updated(
    respx_mock: respx.MockRouter,
) -> None:
    """``knowledge.reindex`` triggers re-indexing and returns refreshed ``last_indexed_at``."""
    reindexed_node = {
        **_BASE_KNOWLEDGE_NODE,
        "lastIndexedAt": "2026-06-21T12:00:00Z",
        "updatedAt": "2026-06-21T12:00:00Z",
    }
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "reindexKnowledge": {
                        "success": True,
                        "errors": [],
                        "knowledge": reindexed_node,
                    }
                }
            },
        )
    )

    async with _client() as c:
        kb = await c.knowledge.reindex("KB:1")

    assert kb.last_indexed_at == "2026-06-21T12:00:00Z"

    body = json.loads(route.calls.last.request.content)
    assert body["variables"] == {"id": "KB:1"}
