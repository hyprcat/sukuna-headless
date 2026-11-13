"""
Thin GraphQL-over-HTTP transport.

Every resource delegates here — wrapping the protocol in one file keeps
swapping it (batching, persisted queries) a one-file change.
"""

from __future__ import annotations

from typing import Any

import httpx

from ._config import ResolvedConfig
from .errors import MidsphereApiError


class GraphQLClient:
    """GraphQL-over-HTTP client backed by a shared ``httpx.AsyncClient``."""

    def __init__(self, config: ResolvedConfig, http: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http

    async def request(
        self,
        query: str,
        variables: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL operation and return ``response["data"]``.

        Raises:

        - ``MidsphereApiError`` on network failures, non-2xx HTTP status, top-level
          GraphQL ``errors``, or an empty/non-JSON response body.
        """
        body = {"query": query, "variables": variables or {}}
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "authorization": f"Bearer {self._config.api_key}",
            **self._config.headers,
        }

        try:
            resp = await self._http.post(
                self._config.graphql_url,
                json=body,
                headers=headers,
                timeout=self._config.timeout,
            )
        except httpx.RequestError as exc:
            raise MidsphereApiError("Network request to midsphere failed.", cause=exc) from exc

        parsed = self._parse_body(resp)

        if not resp.is_success:
            first_message = (
                parsed.get("errors", [{}])[0].get("message")
                if parsed and parsed.get("errors")
                else None
            )
            message = first_message or f"midsphere request failed (HTTP {resp.status_code})."
            raise MidsphereApiError(
                message,
                status=resp.status_code,
                graphql_errors=list(parsed.get("errors") or []) if parsed else [],
            )

        if parsed and parsed.get("errors"):
            errors: list[dict[str, Any]] = list(parsed["errors"])
            raise MidsphereApiError(
                str(errors[0].get("message", "")),
                graphql_errors=errors,
            )

        if parsed is None or parsed.get("data") is None:
            raise MidsphereApiError(
                "midsphere returned an empty response.", status=resp.status_code
            )

        data: dict[str, Any] = parsed["data"]
        return data

    def _parse_body(self, resp: httpx.Response) -> dict[str, Any] | None:
        text = resp.text
        if not text:
            return None
        try:
            return resp.json()  # type: ignore[no-any-return]
        except Exception as exc:
            raise MidsphereApiError(
                "midsphere returned a non-JSON response.",
                status=resp.status_code,
                cause=exc,
            ) from exc
