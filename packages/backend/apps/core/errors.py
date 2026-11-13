"""Closed enum of user-facing error codes for the GraphQL `MutationResult`.

Per BACKEND_CODING_STANDARDS §5: domain failures are part of the contract,
not exceptions. They are projected onto `errors: [UserError!]!` on every
mutation result. The set is intentionally small and closed — adding a code
is a deliberate schema change, not a casual addition.

Top-level GraphQL `errors` is reserved for system failures (auth, rate
limits, internal). Anything a caller can reasonably act on flows through
here.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class UserError(StrEnum):
    """Wire-stable codes surfaced to clients via `MutationResult.errors`.

    Values double as the `code` field of the GraphQL `UserError` type, so
    they must be stable across releases. Renaming a member is a breaking
    change.
    """

    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"
    RUN_LIMIT_EXCEEDED = "RUN_LIMIT_EXCEEDED"
    CONCURRENCY_CAP = "CONCURRENCY_CAP"
    MODEL_TIER_RESTRICTED = "MODEL_TIER_RESTRICTED"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    KNOWLEDGE_NOT_ALLOWED = "KNOWLEDGE_NOT_ALLOWED"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONFLICT = "CONFLICT"
    BILLING_ERROR = "BILLING_ERROR"
    INVALID_API_KEY = "INVALID_API_KEY"
    SCOPE_INSUFFICIENT = "SCOPE_INSUFFICIENT"
    SANDBOX_ERROR = "SANDBOX_ERROR"


def _quota_user_errors() -> frozenset[UserError]:
    return frozenset(
        {
            UserError.INSUFFICIENT_CREDITS,
            UserError.RUN_LIMIT_EXCEEDED,
            UserError.CONCURRENCY_CAP,
            UserError.MODEL_TIER_RESTRICTED,
            UserError.TOOL_NOT_ALLOWED,
            UserError.KNOWLEDGE_NOT_ALLOWED,
        }
    )


class QuotaUserErrors(BaseModel):
    """Subset of `UserError` codes that `QuotaExceeded` is allowed to carry.

    Each value names a per-user-control dimension (credits, run-count,
    concurrency, model tier, allowed tools, allowed knowledge). The
    `QuotaExceeded` constructor in `apps.core.exceptions` validates against
    `QuotaUserErrors().values` so a typo can't smuggle in a non-quota code.
    """

    model_config = ConfigDict(frozen=True)

    values: frozenset[UserError] = Field(default_factory=_quota_user_errors)
