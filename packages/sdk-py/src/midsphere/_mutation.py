"""Helpers shared by all mutation resolvers."""

from __future__ import annotations

from typing import Any

from .errors import MidsphereUserError
from .types import UserError


def ensure_success(payload: dict[str, Any]) -> dict[str, Any]:
    """Assert a mutation payload succeeded.

    Returns the payload unchanged on success. Raises ``MidsphereUserError``
    carrying the domain errors when ``payload["success"]`` is falsy.
    """
    if not payload.get("success"):
        raw_errors = payload.get("errors") or []
        errors = [UserError.from_dict(e) for e in raw_errors]
        raise MidsphereUserError(errors)
    return payload
