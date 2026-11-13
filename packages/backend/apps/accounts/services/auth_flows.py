from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.tasks.emails import send_password_reset_email, send_verification_email
from apps.core.events import record_event

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.accounts.schemas.config import AuthFlowConfig


def create_unverified_user(email: str, password: str, full_name: str) -> User:
    user = User.objects.create_user(email=email, password=password, full_name=full_name)
    send_verification_email.enqueue(user.pk)
    record_event(
        "user_signed_up",
        distinct_id=str(user.pk),
        properties={"email": user.email},
    )
    return user


def request_password_reset(email: str) -> None:
    user = User.objects.filter(email=email, is_active=True).first()
    if user is None or not user.has_usable_password():
        return
    send_password_reset_email.enqueue(user.pk)
    record_event(
        "password_reset_requested",
        distinct_id=str(user.pk),
        properties={"email": user.email},
    )


def password_reset_token_valid(user: User, token: str) -> bool:
    return default_token_generator.check_token(user, token)


def complete_password_reset(user: User, token: str, new_password: str) -> User | None:
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not password_reset_token_valid(locked, token):
            return None
        locked.set_password(new_password)
        locked.save(update_fields=("password", "updated_at"))
    record_event(
        "password_reset_completed",
        distinct_id=str(locked.pk),
        properties={"email": locked.email},
    )
    return locked


def resend_verification(email: str) -> None:
    user = User.objects.filter(email=email, is_active=True).first()
    if user is None or user.is_email_verified:
        return
    send_verification_email.enqueue(user.pk)
    record_event(
        "verification_email_resent",
        distinct_id=str(user.pk),
        properties={"email": user.email},
    )


def login_attempt_key(request: HttpRequest, email: str, config: AuthFlowConfig) -> str:
    return _attempt_key(request, email, config.login_attempt_cache_prefix)


def login_rate_limited(cache_key: str, config: AuthFlowConfig) -> bool:
    return _rate_limited(cache_key, limit=config.login_attempt_limit)


def record_login_failure(cache_key: str, config: AuthFlowConfig) -> None:
    _record_attempt(cache_key, window_seconds=config.login_attempt_window_seconds)


def clear_login_failures(cache_key: str) -> None:
    cache.delete(cache_key)


def password_reset_request_key(request: HttpRequest, email: str, config: AuthFlowConfig) -> str:
    return _attempt_key(request, email, config.reset_request_cache_prefix)


def password_reset_rate_limited(cache_key: str, config: AuthFlowConfig) -> bool:
    return _rate_limited(cache_key, limit=config.password_reset_request_limit)


def record_password_reset_request(cache_key: str, config: AuthFlowConfig) -> None:
    _record_attempt(cache_key, window_seconds=config.password_reset_request_window_seconds)


def verification_resend_key(request: HttpRequest, email: str, config: AuthFlowConfig) -> str:
    return _attempt_key(request, email, config.verification_resend_cache_prefix)


def verification_resend_rate_limited(cache_key: str, config: AuthFlowConfig) -> bool:
    return _rate_limited(cache_key, limit=config.verification_resend_limit)


def record_verification_resend_request(cache_key: str, config: AuthFlowConfig) -> None:
    _record_attempt(cache_key, window_seconds=config.verification_resend_window_seconds)


def audit_login_failure(email: str, reason: str) -> None:
    record_event(
        "login_failed",
        distinct_id=_email_audit_id(email),
        properties={"reason": reason},
    )


def audit_password_reset_request(email: str, reason: str) -> None:
    record_event(
        "password_reset_request_blocked",
        distinct_id=_email_audit_id(email),
        properties={"reason": reason},
    )


def audit_verification_resend(email: str, reason: str) -> None:
    record_event(
        "verification_email_resend_blocked",
        distinct_id=_email_audit_id(email),
        properties={"reason": reason},
    )


def _email_audit_id(email: str) -> str:
    if not email:
        return "anonymous"
    return f"email:{sha256(email.encode()).hexdigest()}"


def _attempt_key(request: HttpRequest, email: str, prefix: str) -> str:
    addr = request.META.get("REMOTE_ADDR", "unknown")
    digest = sha256(f"{email}:{addr}".encode()).hexdigest()
    return f"{prefix}:{digest}"


def _rate_limited(cache_key: str, *, limit: int) -> bool:
    attempts = cache.get(cache_key, 0)
    return int(attempts or 0) >= limit


def _record_attempt(cache_key: str, *, window_seconds: int) -> None:
    if cache.add(cache_key, 1, timeout=window_seconds):
        return
    try:
        cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window_seconds)
