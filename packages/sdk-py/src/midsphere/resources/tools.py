"""Full CRUD lifecycle for the workspace's tools.

Tools can be created, updated, activated, and deactivated. There is no
hard-delete — lifecycle is activate/deactivate only.

Requires the ``tools:read`` scope for queries and ``tools:write`` for mutations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from midsphere._graphql import GraphQLClient
    from midsphere.types import Tool

# Sentinel for distinguishing "caller did not pass this kwarg" from None.
_UNSET: Any = object()

# ---------------------------------------------------------------------------
# Shared field list
# ---------------------------------------------------------------------------

_TOOL_FIELDS = (
    "id name description parametersSchema executionEndpoint "
    "isSensitive isActive createdAt updatedAt deactivatedAt"
)

# ---------------------------------------------------------------------------
# Queries & mutations
# ---------------------------------------------------------------------------

_LIST_TOOLS = f"""
  query Tools($isActive: Boolean, $first: Int) {{
    tools(isActive: $isActive, first: $first) {{
      edges {{
        node {{
          {_TOOL_FIELDS}
        }}
      }}
    }}
  }}
"""

_GET_TOOL = f"""
  query Tool($id: ID!) {{
    tool(id: $id) {{
      {_TOOL_FIELDS}
    }}
  }}
"""

_CREATE_TOOL = f"""
  mutation CreateTool($input: CreateToolInput!) {{
    createTool(input: $input) {{
      success
      errors {{ code field message }}
      tool {{ {_TOOL_FIELDS} }}
    }}
  }}
"""

_UPDATE_TOOL = f"""
  mutation UpdateTool($id: ID!, $input: UpdateToolInput!) {{
    updateTool(id: $id, input: $input) {{
      success
      errors {{ code field message }}
      tool {{ {_TOOL_FIELDS} }}
    }}
  }}
"""

_ACTIVATE_TOOL = f"""
  mutation ActivateTool($id: ID!) {{
    activateTool(id: $id) {{
      success
      errors {{ code field message }}
      tool {{ {_TOOL_FIELDS} }}
    }}
  }}
"""

_DEACTIVATE_TOOL = f"""
  mutation DeactivateTool($id: ID!) {{
    deactivateTool(id: $id) {{
      success
      errors {{ code field message }}
      tool {{ {_TOOL_FIELDS} }}
    }}
  }}
"""

# ---------------------------------------------------------------------------
# Resource class
# ---------------------------------------------------------------------------


class Tools:
    """Full CRUD lifecycle for the workspace's tools.

    Tools can be created, updated, activated, and deactivated. There is no
    hard-delete — lifecycle is activate/deactivate only.

    Requires the ``tools:read`` scope for queries and ``tools:write`` for
    mutations.
    """

    def __init__(self, gql: GraphQLClient) -> None:
        self._gql = gql

    async def list(
        self,
        *,
        is_active: bool | None = None,
        first: int = 50,
    ) -> list[Tool]:
        """Return all tools in the workspace, optionally filtered by active status.

        Args:
            is_active: When set, only returns tools with that active status.
            first: Maximum number of tools to return (default 50).

        Returns:
            A list of Tool objects.
        """
        from midsphere.types import Tool as ToolType

        res = await self._gql.request(
            _LIST_TOOLS,
            {"isActive": is_active, "first": first},
        )
        return [ToolType.from_node(e["node"]) for e in res["tools"]["edges"]]

    async def get(self, id: str) -> Tool | None:
        """Return the tool with the given relay global ID, or None if not found.

        Args:
            id: The relay global ID of the tool.

        Returns:
            The Tool, or None if not found.
        """
        from midsphere.types import Tool as ToolType

        res = await self._gql.request(_GET_TOOL, {"id": id})
        node = res.get("tool")
        return ToolType.from_node(node) if node is not None else None

    async def create(
        self,
        *,
        name: str,
        description: Any = _UNSET,
        parameters_schema: Any = _UNSET,
        execution_endpoint: Any = _UNSET,
        is_sensitive: Any = _UNSET,
    ) -> Tool:
        """Create a new tool. Raises ``MidsphereUserError`` on domain failure.

        Only the keys you provide are sent in the mutation input.

        Args:
            name: The tool's display name (required).
            description: Optional human-readable description.
            parameters_schema: JSON Schema describing the tool's parameters.
            execution_endpoint: URL the backend calls to invoke this tool.
            is_sensitive: When True, output is redacted in run logs.

        Returns:
            The newly created Tool.

        Raises:
            MidsphereUserError: If the backend returns domain errors (e.g. invalid
                input, duplicate name).
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Tool as ToolType

        mutation_input: dict[str, Any] = {"name": name}
        if description is not _UNSET:
            mutation_input["description"] = description
        if parameters_schema is not _UNSET:
            mutation_input["parametersSchema"] = parameters_schema
        if execution_endpoint is not _UNSET:
            mutation_input["executionEndpoint"] = execution_endpoint
        if is_sensitive is not _UNSET:
            mutation_input["isSensitive"] = is_sensitive

        res = await self._gql.request(_CREATE_TOOL, {"input": mutation_input})
        payload = ensure_success(res["createTool"])
        # ensure_success guarantees success=True, so tool is present on the payload
        return ToolType.from_node(payload["tool"])

    async def update(
        self,
        id: str,
        *,
        name: Any = _UNSET,
        description: Any = _UNSET,
        parameters_schema: Any = _UNSET,
        execution_endpoint: Any = _UNSET,
        is_sensitive: Any = _UNSET,
    ) -> Tool:
        """Update mutable fields on an existing tool.

        Omit any field you don't want to change. Raises ``MidsphereUserError``
        on domain failure.

        Args:
            id: Relay global ID of the tool.
            name: New display name.
            description: New description.
            parameters_schema: New JSON Schema for the tool's parameters.
            execution_endpoint: New invocation URL.
            is_sensitive: Whether output should be redacted in run logs.

        Returns:
            The updated Tool.

        Raises:
            MidsphereUserError: If the backend returns domain errors.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Tool as ToolType

        mutation_input: dict[str, Any] = {}
        if name is not _UNSET:
            mutation_input["name"] = name
        if description is not _UNSET:
            mutation_input["description"] = description
        if parameters_schema is not _UNSET:
            mutation_input["parametersSchema"] = parameters_schema
        if execution_endpoint is not _UNSET:
            mutation_input["executionEndpoint"] = execution_endpoint
        if is_sensitive is not _UNSET:
            mutation_input["isSensitive"] = is_sensitive

        res = await self._gql.request(_UPDATE_TOOL, {"id": id, "input": mutation_input})
        payload = ensure_success(res["updateTool"])
        # ensure_success guarantees success=True, so tool is present on the payload
        return ToolType.from_node(payload["tool"])

    async def activate(self, id: str) -> Tool:
        """Activate a previously deactivated tool, making it available for runs.

        Args:
            id: Relay global ID of the tool.

        Returns:
            The updated Tool.

        Raises:
            MidsphereUserError: If the tool does not exist or the transition is
                not allowed.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Tool as ToolType

        res = await self._gql.request(_ACTIVATE_TOOL, {"id": id})
        payload = ensure_success(res["activateTool"])
        # ensure_success guarantees success=True, so tool is present on the payload
        return ToolType.from_node(payload["tool"])

    async def deactivate(self, id: str) -> Tool:
        """Deactivate a tool, preventing it from being used in future runs.

        The tool is not deleted — call ``activate`` to reverse this.

        Args:
            id: Relay global ID of the tool.

        Returns:
            The updated Tool.

        Raises:
            MidsphereUserError: If the tool does not exist or is already
                deactivated.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import Tool as ToolType

        res = await self._gql.request(_DEACTIVATE_TOOL, {"id": id})
        payload = ensure_success(res["deactivateTool"])
        # ensure_success guarantees success=True, so tool is present on the payload
        return ToolType.from_node(payload["tool"])
