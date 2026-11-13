"""Tests for agent, end-user, and rating resources."""

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

_FAKE_AGENT = {
    "id": "QWdlbnRUeXBlOjE=",
    "name": "Support Bot",
    "description": "Handles support tickets.",
    "defaultModelTier": "pro",
    "isActive": True,
}

_FAKE_END_USER = {
    "id": "EU:1",
    "externalUserId": "auth_123",
    "displayName": "Ada",
    "tierLabel": "pro",
    "metadata": {},
    "isActive": True,
}

# ---------------------------------------------------------------------------
# agents.list
# ---------------------------------------------------------------------------


async def test_agents_list_returns_mapped_nodes(respx_mock: respx.MockRouter) -> None:
    """``agents.list`` maps edges to Agent objects."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"agents": {"edges": [{"node": _FAKE_AGENT}]}}},
        )
    )

    async with _client() as c:
        agents = await c.agents.list()

    assert len(agents) == 1
    assert agents[0].id == _FAKE_AGENT["id"]
    assert agents[0].name == _FAKE_AGENT["name"]
    assert agents[0].is_active is True


async def test_agents_list_sends_variables(respx_mock: respx.MockRouter) -> None:
    """``agents.list`` passes ``isActive`` and ``first`` as variables."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"agents": {"edges": []}}})
    )

    async with _client() as c:
        await c.agents.list(is_active=True, first=10)

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["isActive"] is True
    assert body["variables"]["first"] == 10


# ---------------------------------------------------------------------------
# agents.get
# ---------------------------------------------------------------------------


async def test_agents_get_returns_agent(respx_mock: respx.MockRouter) -> None:
    """``agents.get`` returns the Agent when found."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"agent": _FAKE_AGENT}})
    )

    async with _client() as c:
        agent = await c.agents.get("QWdlbnRUeXBlOjE=")

    assert agent is not None
    assert agent.id == "QWdlbnRUeXBlOjE="


async def test_agents_get_returns_none_when_not_found(respx_mock: respx.MockRouter) -> None:
    """``agents.get`` returns ``None`` when the backend returns null."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"agent": None}})
    )

    async with _client() as c:
        agent = await c.agents.get("nonexistent")

    assert agent is None


# ---------------------------------------------------------------------------
# end_users.create
# ---------------------------------------------------------------------------


async def test_end_users_create_returns_end_user(respx_mock: respx.MockRouter) -> None:
    """``end_users.create`` returns the created EndUser."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createEndUser": {
                        "success": True,
                        "errors": [],
                        "endUser": _FAKE_END_USER,
                    }
                }
            },
        )
    )

    async with _client() as c:
        user = await c.end_users.create(external_user_id="auth_123", display_name="Ada")

    assert user.external_user_id == "auth_123"
    assert user.display_name == "Ada"


async def test_end_users_create_sends_only_provided_keys(respx_mock: respx.MockRouter) -> None:
    """Only provided kwargs appear in the ``input`` variable (no sentinel leakage)."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createEndUser": {
                        "success": True,
                        "errors": [],
                        "endUser": _FAKE_END_USER,
                    }
                }
            },
        )
    )

    async with _client() as c:
        await c.end_users.create(external_user_id="auth_123", display_name="Ada")

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["input"] == {
        "externalUserId": "auth_123",
        "displayName": "Ada",
    }


async def test_end_users_create_domain_failure_raises_user_error(
    respx_mock: respx.MockRouter,
) -> None:
    """A domain failure (success=false) raises ``MidsphereUserError``."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "createEndUser": {
                        "success": False,
                        "errors": [
                            {
                                "code": "CONFLICT",
                                "field": "externalUserId",
                                "message": "Already exists",
                            }
                        ],
                        "endUser": None,
                    }
                }
            },
        )
    )

    async with _client() as c:
        with pytest.raises(MidsphereUserError) as exc_info:
            await c.end_users.create(external_user_id="dup")

    assert exc_info.value.code == "CONFLICT"


# ---------------------------------------------------------------------------
# end_users.get
# ---------------------------------------------------------------------------


async def test_end_users_get_returns_end_user(respx_mock: respx.MockRouter) -> None:
    """``end_users.get`` returns the EndUser when found."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"endUser": _FAKE_END_USER}})
    )

    async with _client() as c:
        user = await c.end_users.get("EU:1")

    assert user is not None
    assert user.id == "EU:1"


async def test_end_users_get_returns_none_when_not_found(respx_mock: respx.MockRouter) -> None:
    """``end_users.get`` returns ``None`` when the backend returns null."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"endUser": None}})
    )

    async with _client() as c:
        user = await c.end_users.get("nonexistent")

    assert user is None


# ---------------------------------------------------------------------------
# end_users.list
# ---------------------------------------------------------------------------


async def test_end_users_list_returns_mapped_nodes(respx_mock: respx.MockRouter) -> None:
    """``end_users.list`` maps edges to EndUser objects."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"endUsers": {"edges": [{"node": _FAKE_END_USER}]}}},
        )
    )

    async with _client() as c:
        users = await c.end_users.list()

    assert len(users) == 1
    assert users[0].external_user_id == "auth_123"


# ---------------------------------------------------------------------------
# end_users.get_by_external_id
# ---------------------------------------------------------------------------


async def test_get_by_external_id_exact_matches(respx_mock: respx.MockRouter) -> None:
    """``get_by_external_id`` returns the exact match from fuzzy search results."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "endUsers": {
                        "edges": [
                            {
                                "node": {
                                    "id": "EU:1",
                                    "externalUserId": "auth_1",
                                    "displayName": "",
                                    "tierLabel": "",
                                    "metadata": {},
                                    "isActive": True,
                                }
                            },
                            {
                                "node": {
                                    "id": "EU:2",
                                    "externalUserId": "auth_12",
                                    "displayName": "",
                                    "tierLabel": "",
                                    "metadata": {},
                                    "isActive": True,
                                }
                            },
                        ]
                    }
                }
            },
        )
    )

    async with _client() as c:
        user = await c.end_users.get_by_external_id("auth_1")

    assert user is not None
    assert user.id == "EU:1"


async def test_get_by_external_id_returns_none_on_no_match(
    respx_mock: respx.MockRouter,
) -> None:
    """``get_by_external_id`` returns ``None`` when no exact match is found."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"endUsers": {"edges": []}}},
        )
    )

    async with _client() as c:
        user = await c.end_users.get_by_external_id("nobody")

    assert user is None


# ---------------------------------------------------------------------------
# end_users.ensure
# ---------------------------------------------------------------------------


async def test_ensure_returns_existing_user(respx_mock: respx.MockRouter) -> None:
    """``ensure`` returns the existing user without creating a new one."""
    # The list call (get_by_external_id) returns a match.
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"endUsers": {"edges": [{"node": _FAKE_END_USER}]}}},
        )
    )

    async with _client() as c:
        user = await c.end_users.ensure(external_user_id="auth_123")

    assert user.id == "EU:1"


async def test_ensure_creates_when_not_found(respx_mock: respx.MockRouter) -> None:
    """``ensure`` creates a new user when none exists."""
    # First call: list returns empty; second call: createEndUser succeeds.
    respx_mock.post(GRAPHQL_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": {"endUsers": {"edges": []}}}),
            httpx.Response(
                200,
                json={
                    "data": {
                        "createEndUser": {
                            "success": True,
                            "errors": [],
                            "endUser": _FAKE_END_USER,
                        }
                    }
                },
            ),
        ]
    )

    async with _client() as c:
        user = await c.end_users.ensure(external_user_id="auth_123", display_name="Ada")

    assert user.id == "EU:1"


# ---------------------------------------------------------------------------
# end_users.set_controls
# ---------------------------------------------------------------------------


async def test_set_controls_sends_camel_case_keys(respx_mock: respx.MockRouter) -> None:
    """``set_controls`` serialises Python snake_case kwargs as camelCase GraphQL keys."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "updateEndUserControls": {
                        "success": True,
                        "errors": [],
                        "endUser": _FAKE_END_USER,
                    }
                }
            },
        )
    )

    async with _client() as c:
        await c.end_users.set_controls(
            id="EU:1",
            credit_grant_per_period=100,
            allowed_tool_ids=["T:1", "T:2"],
        )

    body = json.loads(route.calls.last.request.content)
    inp = body["variables"]["input"]
    assert inp["id"] == "EU:1"
    assert inp["creditGrantPerPeriod"] == 100
    assert inp["allowedToolIds"] == ["T:1", "T:2"]
    # Omitted fields must be absent.
    assert "credits" not in inp
    assert "runCountLimit" not in inp


# ---------------------------------------------------------------------------
# ratings.submit
# ---------------------------------------------------------------------------


async def test_ratings_submit_maps_run_uid_to_run_id(respx_mock: respx.MockRouter) -> None:
    """``ratings.submit`` sends the run UID under the GraphQL field name ``runId``."""
    route = respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"submitRating": {"success": True, "errors": []}}},
        )
    )

    async with _client() as c:
        await c.ratings.submit(run_uid="run-uuid", score=5, comment="great")

    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["input"] == {
        "runId": "run-uuid",
        "score": 5,
        "comment": "great",
    }


async def test_ratings_submit_domain_failure_raises_user_error(
    respx_mock: respx.MockRouter,
) -> None:
    """A domain failure on submit raises ``MidsphereUserError``."""
    respx_mock.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "submitRating": {
                        "success": False,
                        "errors": [
                            {
                                "code": "NOT_FOUND",
                                "field": None,
                                "message": "Run not found",
                            }
                        ],
                    }
                }
            },
        )
    )

    async with _client() as c:
        with pytest.raises(MidsphereUserError) as exc_info:
            await c.ratings.submit(run_uid="bad-uid", score=3)

    assert exc_info.value.code == "NOT_FOUND"
