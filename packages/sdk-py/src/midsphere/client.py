"""
The midsphere client — the single entry point.

Construct it with a workspace API key, then run agents and manage end users
and ratings::

    import asyncio
    from midsphere import Midsphere

    async def main():
        async with Midsphere(api_key="ms_prod_...") as client:
            run = await client.run(
                agent_id="QWdlbnRUeXBlOjE=",
                end_user_id="RW5kVXNlclR5cGU6MQ==",
                prompt="Summarize today's signups",
            )
            async for event in run.stream():
                print(event.type, event.payload)

    asyncio.run(main())
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from ._config import resolve_config
from ._graphql import GraphQLClient
from .errors import MidsphereUserError
from .resources import Agents, EndUsers, KnowledgeBases, Ratings, Tools
from .run.run import Run
from .types import UserError

if TYPE_CHECKING:
    from .types import Agent

# ---------------------------------------------------------------------------
# GraphQL operations
# ---------------------------------------------------------------------------

_START_RUN = """
  mutation StartRun($input: StartRunInput!) {
    startRun(input: $input) {
      success
      errors {
        code
        field
        message
      }
      runId
      runUid
      sandboxUrl
      capabilityToken
      tokenExpiresAt
    }
  }
"""

_REFRESH_TOKEN = """
  mutation RefreshSandboxToken($runId: ID!) {
    refreshSandboxToken(runId: $runId) {
      success
      errors {
        code
        field
        message
      }
      capabilityToken
      tokenExpiresAt
    }
  }
"""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class Midsphere:
    """The midsphere Python SDK client.

    All public methods are async. Use as an async context manager to ensure
    the underlying HTTP connection pool is closed cleanly::

        async with Midsphere(api_key="ms_prod_...") as client:
            ...

    Or manage the lifecycle explicitly::

        client = Midsphere(api_key="ms_prod_...")
        try:
            ...
        finally:
            await client.aclose()

    Args:
        api_key: A workspace API key (``ms_prod_...``).
        base_url: Override the default ``https://api.midsphere.com``. Useful
            for local dev (``http://localhost:8000``) and self-hosted deployments.
        timeout: Per-request timeout in seconds. Defaults to 30 s; pass
            ``None`` to disable.
        headers: Extra HTTP headers appended to every GraphQL request.
        http_client: Bring your own ``httpx.AsyncClient`` (proxies, tests,
            custom transports). When supplied the client is **not** closed on
            :meth:`aclose` — the caller owns its lifecycle.
    """

    #: Low-level GraphQL transport. Use for operations not yet wrapped by a
    #: resource.
    gql: GraphQLClient
    #: Read access to the workspace's agents.
    agents: Agents
    #: Create, read, and configure tools.
    tools: Tools
    #: Create, read, and configure knowledge bases.
    knowledge: KnowledgeBases
    #: Create, read, and configure end users.
    end_users: EndUsers
    #: Submit end-user ratings for completed runs.
    ratings: Ratings

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = resolve_config(
            api_key=api_key,
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )
        self._owns_http = http_client is None
        if http_client is not None:
            self._http = http_client
        else:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(self._config.timeout))
        self.gql = GraphQLClient(self._config, self._http)
        self.agents = Agents(self.gql)
        self.tools = Tools(self.gql)
        self.knowledge = KnowledgeBases(self.gql)
        self.end_users = EndUsers(self.gql)
        self.ratings = Ratings(self.gql)

    # -------------------------------------------------------------------------
    # Run
    # -------------------------------------------------------------------------

    async def run(
        self,
        *,
        agent_id: str,
        end_user_id: str,
        prompt: str,
        conversation_uid: str | None = None,
        tool_ids: list[str] | None = None,
        knowledge_ids: list[str] | None = None,
    ) -> Run:
        """Start a run.

        Returns a :class:`~midsphere.run.Run` handle you can stream, wait on,
        cancel, or respond to (for human-in-the-loop). The agent executes in an
        isolated sandbox; events stream directly from it via a short-lived
        capability token.

        Args:
            agent_id: Relay global ID of the agent to run.
            end_user_id: Relay global ID of the end user this run acts on
                behalf of.
            prompt: The instruction the agent receives.
            conversation_uid: Resume an existing conversation thread.
            tool_ids: Whitelist of tool IDs the agent may use. Overrides the
                agent's default tool set.
            knowledge_ids: Whitelist of knowledge IDs the agent may use.

        Returns:
            A :class:`~midsphere.run.Run` handle bound to the started sandbox.

        Raises:
            MidsphereUserError: When the backend rejects the request (insufficient
                credits, concurrency cap, permission denied, etc.).
            MidsphereApiError: On transport or system-level failures.
        """
        run_input = _build_start_run_input(
            agent_id=agent_id,
            end_user_id=end_user_id,
            prompt=prompt,
            conversation_uid=conversation_uid,
            tool_ids=tool_ids,
            knowledge_ids=knowledge_ids,
        )
        data = await self.gql.request(_START_RUN, {"input": run_input})
        payload: dict[str, Any] = data["startRun"]

        if not payload["success"]:
            raise MidsphereUserError([UserError.from_dict(e) for e in payload["errors"]])

        run_id: str = payload["runId"]

        async def _refresh() -> dict[str, Any]:
            return await self._refresh_sandbox_token(run_id)

        return Run(
            run_id=run_id,
            run_uid=payload["runUid"],
            sandbox_url=payload["sandboxUrl"],
            capability_token=payload["capabilityToken"],
            token_expires_at=payload["tokenExpiresAt"],
            http=self._http,
            refresh=_refresh,
        )

    # -------------------------------------------------------------------------
    # Agent handle
    # -------------------------------------------------------------------------

    def agent(self, agent_id: str) -> AgentRef:
        """Return a lightweight handle bound to one agent.

        Sugar over :meth:`run` and :attr:`agents`.get — useful when all your
        calls target the same agent::

            agent = client.agent("QWdlbnRUeXBlOjE=")
            run = await agent.run(end_user_id=uid, prompt="Hello")
        """
        return AgentRef(self, agent_id)

    # -------------------------------------------------------------------------
    # Internal: token refresh
    # -------------------------------------------------------------------------

    async def _refresh_sandbox_token(self, run_id: str) -> dict[str, Any]:
        """Refresh the short-lived capability token for an active run.

        Returns a dict with ``capability_token`` and ``token_expires_at``.

        Raises:
            MidsphereUserError: When the backend rejects the refresh.
            MidsphereApiError: On transport failures.
        """
        data = await self.gql.request(_REFRESH_TOKEN, {"runId": run_id})
        payload: dict[str, Any] = data["refreshSandboxToken"]

        if not payload["success"]:
            raise MidsphereUserError([UserError.from_dict(e) for e in payload["errors"]])

        return {
            "capability_token": payload["capabilityToken"],
            "token_expires_at": payload["tokenExpiresAt"],
        }

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool.

        No-op when the client was constructed with a caller-supplied
        ``http_client`` — in that case the caller owns the lifecycle.
        """
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> Midsphere:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


# ---------------------------------------------------------------------------
# AgentRef
# ---------------------------------------------------------------------------


class AgentRef:
    """Bound-agent convenience handle returned by :meth:`Midsphere.agent`.

    Delegates :meth:`run` and :meth:`get` to the parent client with
    ``agent_id`` already filled in.
    """

    #: The agent's Relay global ID.
    id: str

    def __init__(self, client: Midsphere, agent_id: str) -> None:
        self._client = client
        self.id = agent_id

    async def run(
        self,
        *,
        end_user_id: str,
        prompt: str,
        conversation_uid: str | None = None,
        tool_ids: list[str] | None = None,
        knowledge_ids: list[str] | None = None,
    ) -> Run:
        """Start a run for this agent.

        Equivalent to ``client.run(agent_id=self.id, ...)``.
        """
        return await self._client.run(
            agent_id=self.id,
            end_user_id=end_user_id,
            prompt=prompt,
            conversation_uid=conversation_uid,
            tool_ids=tool_ids,
            knowledge_ids=knowledge_ids,
        )

    async def get(self) -> Agent | None:
        """Fetch this agent's configuration from the control plane.

        Returns ``None`` when the agent is not found.
        """
        return await self._client.agents.get(self.id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_start_run_input(
    *,
    agent_id: str,
    end_user_id: str,
    prompt: str,
    conversation_uid: str | None,
    tool_ids: list[str] | None,
    knowledge_ids: list[str] | None,
) -> dict[str, Any]:
    """Build the StartRunInput dict, omitting optional fields the caller didn't set."""
    out: dict[str, Any] = {
        "agentId": agent_id,
        "endUserId": end_user_id,
        "prompt": prompt,
    }
    if conversation_uid is not None:
        out["conversationUid"] = conversation_uid
    if tool_ids is not None:
        out["toolIds"] = tool_ids
    if knowledge_ids is not None:
        out["knowledgeIds"] = knowledge_ids
    return out
