"""Create, read, and manage the workspace's knowledge bases.

Knowledge bases are document stores, datasets, or connected sources that
agents can retrieve context from during a run. The lifecycle is
activate/deactivate — there is no hard-delete.

Access requires the ``knowledge:read`` scope for queries and
``knowledge:write`` for mutations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from midsphere._graphql import GraphQLClient
    from midsphere.types import Knowledge

# Sentinel for distinguishing "caller did not pass this kwarg" from None.
_UNSET: Any = object()

# ---------------------------------------------------------------------------
# Shared field list
# ---------------------------------------------------------------------------

_KNOWLEDGE_FIELDS = (
    "id name description kind fileName fileSizeBytes contentType "
    "sourceEndpoint isActive createdAt updatedAt lastIndexedAt deactivatedAt"
)

# ---------------------------------------------------------------------------
# Queries & mutations
# ---------------------------------------------------------------------------

_LIST_KNOWLEDGE_BASES = f"""
  query KnowledgeBases($kind: String, $isActive: Boolean, $first: Int) {{
    knowledgeBases(kind: $kind, isActive: $isActive, first: $first) {{
      edges {{
        node {{
          {_KNOWLEDGE_FIELDS}
        }}
      }}
    }}
  }}
"""

_GET_KNOWLEDGE_BASE = f"""
  query KnowledgeBase($id: ID!) {{
    knowledgeBase(id: $id) {{
      {_KNOWLEDGE_FIELDS}
    }}
  }}
"""

_CREATE_KNOWLEDGE = f"""
  mutation CreateKnowledge($input: CreateKnowledgeInput!) {{
    createKnowledge(input: $input) {{
      success
      errors {{ code field message }}
      knowledge {{ {_KNOWLEDGE_FIELDS} }}
    }}
  }}
"""

_UPDATE_KNOWLEDGE = f"""
  mutation UpdateKnowledge($id: ID!, $input: UpdateKnowledgeInput!) {{
    updateKnowledge(id: $id, input: $input) {{
      success
      errors {{ code field message }}
      knowledge {{ {_KNOWLEDGE_FIELDS} }}
    }}
  }}
"""

_ACTIVATE_KNOWLEDGE = f"""
  mutation ActivateKnowledge($id: ID!) {{
    activateKnowledge(id: $id) {{
      success
      errors {{ code field message }}
      knowledge {{ {_KNOWLEDGE_FIELDS} }}
    }}
  }}
"""

_DEACTIVATE_KNOWLEDGE = f"""
  mutation DeactivateKnowledge($id: ID!) {{
    deactivateKnowledge(id: $id) {{
      success
      errors {{ code field message }}
      knowledge {{ {_KNOWLEDGE_FIELDS} }}
    }}
  }}
"""

_REINDEX_KNOWLEDGE = f"""
  mutation ReindexKnowledge($id: ID!) {{
    reindexKnowledge(id: $id) {{
      success
      errors {{ code field message }}
      knowledge {{ {_KNOWLEDGE_FIELDS} }}
    }}
  }}
"""

# ---------------------------------------------------------------------------
# Resource class
# ---------------------------------------------------------------------------


class KnowledgeBases:
    """Create, read, and manage the workspace's knowledge bases.

    Knowledge bases are document stores, datasets, or connected sources that
    agents can retrieve context from during a run. The lifecycle is
    activate/deactivate — there is no hard-delete.

    Access requires the ``knowledge:read`` scope for queries and
    ``knowledge:write`` for mutations.
    """

    def __init__(self, gql: GraphQLClient) -> None:
        self._gql = gql

    async def list(
        self,
        *,
        kind: str | None = None,
        is_active: bool | None = None,
        first: int = 50,
    ) -> list[Knowledge]:
        """Return all knowledge bases in the workspace, optionally filtered.

        Args:
            kind: When set, only returns knowledge bases of that kind
                (e.g. ``'document'``, ``'dataset'``, ``'connected_source'``).
            is_active: When set, only returns knowledge bases with that
                active status.
            first: Maximum number of results to return (default 50).

        Returns:
            A list of Knowledge objects.
        """
        from midsphere.types import Knowledge as KnowledgeType

        res = await self._gql.request(
            _LIST_KNOWLEDGE_BASES,
            {"kind": kind, "isActive": is_active, "first": first},
        )
        return [KnowledgeType.from_node(e["node"]) for e in res["knowledgeBases"]["edges"]]

    async def get(self, id: str) -> Knowledge | None:
        """Return the knowledge base with the given relay global ID, or None.

        Args:
            id: Relay global ID of the knowledge base.

        Returns:
            The Knowledge, or None if not found.
        """
        from midsphere.types import Knowledge as KnowledgeType

        res = await self._gql.request(_GET_KNOWLEDGE_BASE, {"id": id})
        node = res.get("knowledgeBase")
        return KnowledgeType.from_node(node) if node is not None else None

    async def create(
        self,
        *,
        name: str,
        kind: str,
        description: Any = _UNSET,
        source_endpoint: Any = _UNSET,
        source_config: Any = _UNSET,
    ) -> Knowledge:
        """Create a new knowledge base. Raises ``MidsphereUserError`` on domain failure.

        Args:
            name: Human-readable name for the knowledge base.
            kind: One of ``'document'``, ``'dataset'``, or ``'connected_source'``.
            description: Optional description.
            source_endpoint: Optional URL for connected sources.
            source_config: Optional JSON config for connected sources.

        Returns:
            The newly created Knowledge.

        Raises:
            MidsphereUserError: If the backend returns domain errors (e.g.
                duplicate name, invalid kind).
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Knowledge as KnowledgeType

        mutation_input: dict[str, Any] = {"name": name, "kind": kind}
        if description is not _UNSET:
            mutation_input["description"] = description
        if source_endpoint is not _UNSET:
            mutation_input["sourceEndpoint"] = source_endpoint
        if source_config is not _UNSET:
            mutation_input["sourceConfig"] = source_config

        res = await self._gql.request(_CREATE_KNOWLEDGE, {"input": mutation_input})
        payload = ensure_success(res["createKnowledge"])
        # ensure_success guarantees success=True, so knowledge is present
        return KnowledgeType.from_node(payload["knowledge"])

    async def update(
        self,
        id: str,
        *,
        name: Any = _UNSET,
        description: Any = _UNSET,
        source_endpoint: Any = _UNSET,
        source_config: Any = _UNSET,
    ) -> Knowledge:
        """Update mutable fields on an existing knowledge base.

        Omit any field you don't want to change.

        Args:
            id: Relay global ID of the knowledge base.
            name: New display name.
            description: New description.
            source_endpoint: New URL for connected sources.
            source_config: New JSON config for connected sources.

        Returns:
            The updated Knowledge.

        Raises:
            MidsphereUserError: If the backend returns domain errors.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Knowledge as KnowledgeType

        mutation_input: dict[str, Any] = {}
        if name is not _UNSET:
            mutation_input["name"] = name
        if description is not _UNSET:
            mutation_input["description"] = description
        if source_endpoint is not _UNSET:
            mutation_input["sourceEndpoint"] = source_endpoint
        if source_config is not _UNSET:
            mutation_input["sourceConfig"] = source_config

        res = await self._gql.request(_UPDATE_KNOWLEDGE, {"id": id, "input": mutation_input})
        payload = ensure_success(res["updateKnowledge"])
        # ensure_success guarantees success=True, so knowledge is present
        return KnowledgeType.from_node(payload["knowledge"])

    async def activate(self, id: str) -> Knowledge:
        """Activate a previously deactivated knowledge base.

        Makes the knowledge base available to agents during runs.

        Args:
            id: Relay global ID of the knowledge base.

        Returns:
            The updated Knowledge.

        Raises:
            MidsphereUserError: On domain failure.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Knowledge as KnowledgeType

        res = await self._gql.request(_ACTIVATE_KNOWLEDGE, {"id": id})
        payload = ensure_success(res["activateKnowledge"])
        # ensure_success guarantees success=True, so knowledge is present
        return KnowledgeType.from_node(payload["knowledge"])

    async def deactivate(self, id: str) -> Knowledge:
        """Deactivate a knowledge base so it is no longer available to agents.

        There is no hard-delete — call ``activate`` to reverse this.

        Args:
            id: Relay global ID of the knowledge base.

        Returns:
            The updated Knowledge.

        Raises:
            MidsphereUserError: On domain failure.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Knowledge as KnowledgeType

        res = await self._gql.request(_DEACTIVATE_KNOWLEDGE, {"id": id})
        payload = ensure_success(res["deactivateKnowledge"])
        # ensure_success guarantees success=True, so knowledge is present
        return KnowledgeType.from_node(payload["knowledge"])

    async def reindex(self, id: str) -> Knowledge:
        """Trigger a re-index of the knowledge base's content.

        Use this after uploading new documents or updating a connected source.
        Returns the updated knowledge base with a refreshed ``last_indexed_at``.

        Args:
            id: Relay global ID of the knowledge base.

        Returns:
            The updated Knowledge with a refreshed ``last_indexed_at``.

        Raises:
            MidsphereUserError: On domain failure.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Knowledge as KnowledgeType

        res = await self._gql.request(_REINDEX_KNOWLEDGE, {"id": id})
        payload = ensure_success(res["reindexKnowledge"])
        # ensure_success guarantees success=True, so knowledge is present
        return KnowledgeType.from_node(payload["knowledge"])
