"""Domain exception hierarchy.

Each exception carries the matching `UserError` so the resolver-level mapper
can project it onto `MutationResult.errors` without a per-site `try/except`
ladder. Raised in models / services; caught once at the resolver boundary.

Per BACKEND_CODING_STANDARDS §3, domain failures are exceptions internally
and `UserError`s on the wire — never raw GraphQL `errors`.
"""

from __future__ import annotations

from typing import ClassVar

from apps.core.errors import QuotaUserErrors, UserError


class DomainError(Exception):
    """Base for every failure a caller can reasonably act on.

    Subclasses pin a `code: ClassVar[UserError]`; `QuotaExceeded` overrides it
    per-instance because the same exception covers several quota dimensions.
    """

    code: ClassVar[UserError]

    def __init__(self, message: str = "", *, field: str | None = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.field = field

    @property
    def user_error_code(self) -> UserError:
        """Resolve the wire-level code for this exception instance."""
        return self.code


class NotFound(DomainError):
    code = UserError.NOT_FOUND


class PermissionDenied(DomainError):
    code = UserError.PERMISSION_DENIED


class InvalidInput(DomainError):
    code = UserError.INVALID_INPUT


class Conflict(DomainError):
    code = UserError.CONFLICT


class BillingError(DomainError):
    code = UserError.BILLING_ERROR


class InvalidApiKey(DomainError):
    code = UserError.INVALID_API_KEY


class ScopeInsufficient(DomainError):
    code = UserError.SCOPE_INSUFFICIENT


class SandboxError(DomainError):
    code = UserError.SANDBOX_ERROR


class QuotaExceeded(DomainError):
    """One exception, several quota dimensions.

    The constructor takes the specific `UserError` describing which control
    tripped — credits, run-count, concurrency, model tier, allowed tools, or
    allowed knowledge. Keeps the per-user-control checker on `EndUser` from
    needing six near-identical exception classes.
    """

    code = UserError.INSUFFICIENT_CREDITS  # default; overridden per-instance

    def __init__(
        self,
        code: UserError,
        message: str = "",
        *,
        field: str | None = None,
    ) -> None:
        if code not in QuotaUserErrors().values:
            raise ValueError(f"QuotaExceeded code must be a quota UserError, got {code!r}")
        super().__init__(message, field=field)
        self._instance_code = code

    @property
    def user_error_code(self) -> UserError:
        return self._instance_code
