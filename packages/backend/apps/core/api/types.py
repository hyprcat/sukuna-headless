from __future__ import annotations

import strawberry


@strawberry.type(description="A domain-level error surfaced to clients.")
class UserErrorType:
    code: str
    field: str | None = None
    message: str

    @classmethod
    def from_domain(cls, exc: Exception) -> UserErrorType:
        from apps.core.exceptions import DomainError  # noqa: PLC0415

        if not isinstance(exc, DomainError):
            return cls(code="INTERNAL", message=str(exc))
        return cls(
            code=exc.user_error_code.value,
            field=exc.field,
            message=exc.message,
        )


@strawberry.interface(description="Uniform mutation response shape.")
class MutationResult:
    success: bool
    errors: list[UserErrorType]
