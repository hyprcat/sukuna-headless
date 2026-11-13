from __future__ import annotations

from collections.abc import Iterable
from functools import wraps
from typing import TYPE_CHECKING, Any

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError

from apps.core.api.types import UserErrorType
from apps.core.errors import UserError
from apps.core.exceptions import DomainError

if TYPE_CHECKING:
    from collections.abc import Callable


def catch_domain_errors[T](
    payload_cls: type[T],
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Catch domain failures and return a failed mutation payload."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return fn(*args, **kwargs)
            except DomainError as exc:
                return _domain_payload(payload_cls, exc)
            except ValidationError as exc:
                return _invalid_payload(payload_cls, exc)
            except IntegrityError:
                return _conflict_payload(payload_cls)

        return wrapper

    return decorator


def _domain_payload[T](payload_cls: type[T], exc: DomainError) -> T:
    error = UserErrorType.from_domain(exc)
    return payload_cls(success=False, errors=[error])  # type: ignore[call-arg]


def _invalid_payload[T](payload_cls: type[T], exc: ValidationError) -> T:
    return payload_cls(  # type: ignore[call-arg]
        success=False,
        errors=_validation_errors(exc),
    )


def _conflict_payload[T](payload_cls: type[T]) -> T:
    return payload_cls(  # type: ignore[call-arg]
        success=False,
        errors=[
            UserErrorType(
                code=UserError.CONFLICT.value,
                message="A conflicting record already exists.",
            )
        ],
    )


def _validation_errors(exc: ValidationError) -> list[UserErrorType]:
    message_dict = getattr(exc, "message_dict", None)
    if message_dict:
        return [_validation_error(field, messages) for field, messages in message_dict.items()]
    return [
        UserErrorType(
            code=UserError.INVALID_INPUT.value,
            message=_join_messages(exc.messages),
        )
    ]


def _validation_error(field: str, messages: object) -> UserErrorType:
    return UserErrorType(
        code=UserError.INVALID_INPUT.value,
        field=None if field == NON_FIELD_ERRORS else field,
        message=_join_messages(messages),
    )


def _join_messages(messages: object) -> str:
    if isinstance(messages, ValidationError):
        return " ".join(messages.messages)
    if isinstance(messages, str):
        return messages
    if isinstance(messages, Iterable):
        return " ".join(str(message) for message in messages)
    return str(messages)
