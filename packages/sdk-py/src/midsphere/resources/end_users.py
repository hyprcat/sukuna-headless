"""Create, read, and configure the developer's end users."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from midsphere._graphql import GraphQLClient
    from midsphere.types import EndUser

# Sentinel for distinguishing "caller did not pass this kwarg" from None.
# Important for control fields like run_count_limit that legitimately accept None.
_UNSET: Any = object()

# ---------------------------------------------------------------------------
# Shared field list
# ---------------------------------------------------------------------------

_END_USER_FIELDS = "id externalUserId displayName tierLabel metadata isActive"

# ---------------------------------------------------------------------------
# Queries & mutations
# ---------------------------------------------------------------------------

_LIST_END_USERS = f"""
  query EndUsers($search: String, $isActive: Boolean, $first: Int) {{
    endUsers(search: $search, isActive: $isActive, first: $first) {{
      edges {{
        node {{
          {_END_USER_FIELDS}
        }}
      }}
    }}
  }}
"""

_GET_END_USER = f"""
  query EndUser($id: ID!) {{
    endUser(id: $id) {{
      {_END_USER_FIELDS}
    }}
  }}
"""

_CREATE_END_USER = f"""
  mutation CreateEndUser($input: CreateEndUserInput!) {{
    createEndUser(input: $input) {{
      success
      errors {{ code field message }}
      endUser {{ {_END_USER_FIELDS} }}
    }}
  }}
"""

_UPDATE_END_USER = f"""
  mutation UpdateEndUser($id: ID!, $input: UpdateEndUserInput!) {{
    updateEndUser(id: $id, input: $input) {{
      success
      errors {{ code field message }}
      endUser {{ {_END_USER_FIELDS} }}
    }}
  }}
"""

_UPDATE_END_USER_CONTROLS = f"""
  mutation UpdateEndUserControls($input: UpdateEndUserControlsInput!) {{
    updateEndUserControls(input: $input) {{
      success
      errors {{ code field message }}
      endUser {{ {_END_USER_FIELDS} }}
    }}
  }}
"""

# ---------------------------------------------------------------------------
# Resource class
# ---------------------------------------------------------------------------


class EndUsers:
    """Create, read, and configure the developer's end users."""

    def __init__(self, gql: GraphQLClient) -> None:
        self._gql = gql

    async def create(
        self,
        *,
        external_user_id: str,
        display_name: Any = _UNSET,
        tier_label: Any = _UNSET,
        metadata: Any = _UNSET,
    ) -> EndUser:
        """Create a new end user. Raises ``MidsphereUserError`` on domain failure.

        Args:
            external_user_id: Your system's stable identifier for this user.
            display_name: Optional human-readable name shown in the dashboard.
            tier_label: Optional tier label (e.g. ``'pro'``, ``'free'``).
            metadata: Optional freeform metadata dict.

        Returns:
            The newly created EndUser.

        Raises:
            MidsphereUserError: If the backend returns domain errors (e.g.
                duplicate ``externalUserId``).
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import EndUser as EndUserType

        mutation_input: dict[str, Any] = {"externalUserId": external_user_id}
        if display_name is not _UNSET:
            mutation_input["displayName"] = display_name
        if tier_label is not _UNSET:
            mutation_input["tierLabel"] = tier_label
        # The backend's CreateEndUserInput.metadata is required (JSON!); default
        # to an empty object when the caller doesn't supply one.
        mutation_input["metadata"] = metadata if metadata is not _UNSET else {}

        res = await self._gql.request(_CREATE_END_USER, {"input": mutation_input})
        payload = ensure_success(res["createEndUser"])
        # ensure_success guarantees success=True, so endUser is present on the payload
        return EndUserType.from_node(payload["endUser"])

    async def update(
        self,
        id: str,
        *,
        display_name: Any = _UNSET,
        tier_label: Any = _UNSET,
        metadata: Any = _UNSET,
    ) -> EndUser:
        """Update mutable fields on an existing end user.

        Omit any field you don't want to change.

        Args:
            id: Relay global ID of the end user.
            display_name: New human-readable name.
            tier_label: New tier label.
            metadata: New freeform metadata dict.

        Returns:
            The updated EndUser.

        Raises:
            MidsphereUserError: If the backend returns domain errors.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import EndUser as EndUserType

        mutation_input: dict[str, Any] = {}
        if display_name is not _UNSET:
            mutation_input["displayName"] = display_name
        if tier_label is not _UNSET:
            mutation_input["tierLabel"] = tier_label
        if metadata is not _UNSET:
            mutation_input["metadata"] = metadata

        res = await self._gql.request(_UPDATE_END_USER, {"id": id, "input": mutation_input})
        payload = ensure_success(res["updateEndUser"])
        # ensure_success guarantees success=True, so endUser is present on the payload
        return EndUserType.from_node(payload["endUser"])

    async def list(
        self,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        first: int = 50,
    ) -> list[EndUser]:
        """Return all end users in the workspace.

        Args:
            search: Fuzzy search string matched against display name and
                external user ID.
            is_active: When set, filters by active status.
            first: Maximum number of end users to return (default 50).

        Returns:
            A list of EndUser objects.
        """
        from midsphere.types import EndUser as EndUserType

        res = await self._gql.request(
            _LIST_END_USERS,
            {"search": search, "isActive": is_active, "first": first},
        )
        return [EndUserType.from_node(e["node"]) for e in res["endUsers"]["edges"]]

    async def get(self, id: str) -> EndUser | None:
        """Return the end user with the given relay global ID, or None.

        Args:
            id: Relay global ID of the end user.

        Returns:
            The EndUser, or None if not found.
        """
        from midsphere.types import EndUser as EndUserType

        res = await self._gql.request(_GET_END_USER, {"id": id})
        node = res.get("endUser")
        return EndUserType.from_node(node) if node is not None else None

    async def get_by_external_id(self, external_user_id: str) -> EndUser | None:
        """Look up an end user by your system's external identifier.

        The backend ``search`` filter is a fuzzy icontains match, so this method
        performs an exact match locally after fetching candidates.

        Args:
            external_user_id: Your system's stable identifier for this user.

        Returns:
            The EndUser, or None if not found.
        """
        candidates = await self.list(search=external_user_id, first=50)
        for user in candidates:
            if user.external_user_id == external_user_id:
                return user
        return None

    async def ensure(
        self,
        *,
        external_user_id: str,
        display_name: Any = _UNSET,
        tier_label: Any = _UNSET,
        metadata: Any = _UNSET,
    ) -> EndUser:
        """Return the existing end user, or create one if none exists.

        Useful for idempotent user provisioning at run time.

        Args:
            external_user_id: Your system's stable identifier for this user.
            display_name: Optional human-readable name (used on create only).
            tier_label: Optional tier label (used on create only).
            metadata: Optional freeform metadata dict (used on create only).

        Returns:
            The existing or newly created EndUser.
        """
        existing = await self.get_by_external_id(external_user_id)
        if existing is not None:
            return existing
        return await self.create(
            external_user_id=external_user_id,
            display_name=display_name,
            tier_label=tier_label,
            metadata=metadata,
        )

    async def set_controls(
        self,
        *,
        id: str,
        credits: Any = _UNSET,
        credit_grant_per_period: Any = _UNSET,
        run_count_limit: Any = _UNSET,
        run_count_period: Any = _UNSET,
        sandbox_time_seconds: Any = _UNSET,
        concurrency_max: Any = _UNSET,
        model_tier: Any = _UNSET,
        credit_refresh_schedule: Any = _UNSET,
        allowed_tool_ids: Any = _UNSET,
        allowed_knowledge_ids: Any = _UNSET,
    ) -> EndUser:
        """Update the per-user control levers.

        Controls credits, rate limits, model tier, and allowed tools/knowledge.
        Only the keys you provide are changed.

        Args:
            id: Relay global ID of the end user.
            credits: Credit balance to set.
            credit_grant_per_period: Credits granted per refresh period.
            run_count_limit: Maximum runs allowed per period (None to unset).
            run_count_period: The period length for run count limits.
            sandbox_time_seconds: Maximum sandbox seconds per run.
            concurrency_max: Maximum concurrent runs for this user.
            model_tier: Model tier restriction (e.g. ``'standard'``, ``'pro'``).
            credit_refresh_schedule: Cron expression for credit refresh.
            allowed_tool_ids: Relay global IDs of tools this user may access.
            allowed_knowledge_ids: Relay global IDs of knowledge bases this
                user may access.

        Returns:
            The updated EndUser.

        Raises:
            MidsphereUserError: If the backend returns domain errors.
        """
        from midsphere._mutation import ensure_success
        from midsphere.types import EndUser as EndUserType

        mutation_input: dict[str, Any] = {"id": id}
        if credits is not _UNSET:
            mutation_input["credits"] = credits
        if credit_grant_per_period is not _UNSET:
            mutation_input["creditGrantPerPeriod"] = credit_grant_per_period
        if run_count_limit is not _UNSET:
            mutation_input["runCountLimit"] = run_count_limit
        if run_count_period is not _UNSET:
            mutation_input["runCountPeriod"] = run_count_period
        if sandbox_time_seconds is not _UNSET:
            mutation_input["sandboxTimeSeconds"] = sandbox_time_seconds
        if concurrency_max is not _UNSET:
            mutation_input["concurrencyMax"] = concurrency_max
        if model_tier is not _UNSET:
            mutation_input["modelTier"] = model_tier
        if credit_refresh_schedule is not _UNSET:
            mutation_input["creditRefreshSchedule"] = credit_refresh_schedule
        if allowed_tool_ids is not _UNSET:
            mutation_input["allowedToolIds"] = allowed_tool_ids
        if allowed_knowledge_ids is not _UNSET:
            mutation_input["allowedKnowledgeIds"] = allowed_knowledge_ids

        res = await self._gql.request(_UPDATE_END_USER_CONTROLS, {"input": mutation_input})
        payload = ensure_success(res["updateEndUserControls"])
        # ensure_success guarantees success=True, so endUser is present on the payload
        return EndUserType.from_node(payload["endUser"])
