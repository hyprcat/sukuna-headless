"""Read access to the workspace's agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from midsphere._graphql import GraphQLClient
    from midsphere.types import Agent

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_LIST_AGENTS = """
  query Agents($isActive: Boolean, $first: Int) {
    agents(isActive: $isActive, first: $first) {
      edges {
        node {
          id
          name
          description
          defaultModelTier
          isActive
        }
      }
    }
  }
"""

_GET_AGENT = """
  query Agent($id: ID!) {
    agent(id: $id) {
      id
      name
      description
      defaultModelTier
      isActive
    }
  }
"""

# ---------------------------------------------------------------------------
# Resource class
# ---------------------------------------------------------------------------


class Agents:
    """Read access to the agents configured in the workspace."""

    def __init__(self, gql: GraphQLClient) -> None:
        self._gql = gql

    async def list(
        self,
        *,
        is_active: bool | None = None,
        first: int = 50,
    ) -> list[Agent]:
        """Return all agents in the workspace, optionally filtered by active status.

        Args:
            is_active: When set, only returns agents with that active status.
            first: Maximum number of agents to return (default 50).

        Returns:
            A list of Agent objects.
        """
        from midsphere.types import Agent as AgentType

        res = await self._gql.request(
            _LIST_AGENTS,
            {"isActive": is_active, "first": first},
        )
        return [AgentType.from_node(e["node"]) for e in res["agents"]["edges"]]

    async def get(self, id: str) -> Agent | None:
        """Return the agent with the given relay global ID, or None if not found.

        Args:
            id: The relay global ID of the agent.

        Returns:
            The Agent, or None if not found.
        """
        from midsphere.types import Agent as AgentType

        res = await self._gql.request(_GET_AGENT, {"id": id})
        node = res.get("agent")
        return AgentType.from_node(node) if node is not None else None
