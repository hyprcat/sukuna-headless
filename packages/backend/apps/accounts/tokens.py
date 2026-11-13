from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.tokens import PasswordResetTokenGenerator

if TYPE_CHECKING:
    from apps.accounts.models import User


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Token for verifying the account's current email address.

    The hash omits ``email_verified_at`` so reopening a still-valid link can
    return an idempotent already-verified response without side effects.
    """

    key_salt = "apps.accounts.tokens.EmailVerificationTokenGenerator"

    def _make_hash_value(self, user: User, timestamp: int) -> str:
        login_ts = ""
        if user.last_login:
            login_ts = user.last_login.replace(
                microsecond=0,
                tzinfo=None,
            ).isoformat()
        return f"{user.pk}{user.password}{timestamp}{login_ts}{user.email}"


def make_email_verification_token(user: User) -> str:
    return EmailVerificationTokenGenerator().make_token(user)


def check_email_verification_token(user: User, token: str) -> bool:
    return EmailVerificationTokenGenerator().check_token(user, token)
