from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.midsphere.com"
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Fully-resolved configuration with defaults applied. Internal."""

    api_key: str
    graphql_url: str
    headers: dict[str, str]
    timeout: float


def resolve_config(
    *,
    api_key: str,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> ResolvedConfig:
    """Validate and resolve client options, applying defaults.

    Raises ``ValueError`` when ``api_key`` is empty or missing.
    """
    if not api_key:
        raise ValueError("midsphere: `api_key` is required.")
    graphql_url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/graphql/"
    return ResolvedConfig(
        api_key=api_key,
        graphql_url=graphql_url,
        headers=dict(headers) if headers else {},
        timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
    )
