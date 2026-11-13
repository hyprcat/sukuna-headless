"""
Error types raised by the midsphere SDK.

All errors are subclasses of ``MidsphereError`` — ``except MidsphereError``
catches everything the SDK raises.
"""

from __future__ import annotations

from collections.abc import Sequence

from .types import UserError


class MidsphereError(Exception):
    """Base class for every error the midsphere SDK raises."""


class MidsphereApiError(MidsphereError):
    """Transport- or system-level failure talking to the GraphQL surface.

    Covers non-2xx responses, network errors, and top-level GraphQL ``errors``
    (auth, rate limit, internal). Domain failures are ``MidsphereUserError``,
    not this.
    """

    status: int | None
    graphql_errors: list[dict[str, object]]

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        graphql_errors: list[dict[str, object]] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.graphql_errors = graphql_errors if graphql_errors is not None else []
        if cause is not None:
            self.__cause__ = cause


class MidsphereUserError(MidsphereError):
    """A domain failure surfaced through a mutation's ``MutationResult.errors``.

    Carries the full list; ``code``, ``field``, and the exception message
    reflect the first error for convenience.
    """

    errors: list[UserError]
    code: str
    field: str | None

    def __init__(self, errors: Sequence[UserError]) -> None:
        first = errors[0] if errors else None
        super().__init__(first.message if first else "The request was rejected.")
        self.errors = list(errors)
        self.code = first.code if first else "INVALID_INPUT"
        self.field = first.field if first else None

    def has(self, code: str) -> bool:
        """Return ``True`` when any error in the list carries ``code``."""
        return any(e.code == code for e in self.errors)


class MidsphereStreamError(MidsphereError):
    """A failure talking directly to the sandbox over HTTP (stream, cancel, HITL)."""

    status: int | None

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        if cause is not None:
            self.__cause__ = cause
