from __future__ import annotations

from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.tasks import task
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from pydantic import BaseModel, ConfigDict

from apps.accounts.tokens import make_email_verification_token
from config.runtime import runtime


class EmailSubjects(BaseModel):
    model_config = ConfigDict(frozen=True)

    verify: str = "Verify your email — midsphere"
    reset: str = "Reset your password — midsphere"


def _build_uid(user_pk: int) -> str:
    return urlsafe_base64_encode(force_bytes(user_pk))


@task
def send_verification_email(user_id: int) -> None:
    from apps.accounts.models import User  # noqa: PLC0415

    user = User.objects.filter(pk=user_id).first()
    if user is None or user.is_email_verified:
        return
    uid = _build_uid(user.pk)
    token = make_email_verification_token(user)
    link = f"{runtime.frontend_url}/verify-email/{uid}/{token}"
    body = (
        f"Verify your email to start using midsphere:\n\n{link}\n\nThis link expires in one hour."
    )
    send_mail(
        subject=EmailSubjects().verify,
        message=body,
        from_email=None,
        recipient_list=[user.email],
    )


@task
def send_password_reset_email(user_id: int) -> None:
    from apps.accounts.models import User  # noqa: PLC0415

    user = User.objects.filter(pk=user_id).first()
    if user is None or not user.is_active:
        return
    uid = _build_uid(user.pk)
    token = default_token_generator.make_token(user)
    send_mail(
        subject=EmailSubjects().reset,
        message=_password_reset_body(uid=uid, token=token),
        from_email=None,
        recipient_list=[user.email],
    )


def _password_reset_body(*, uid: str, token: str) -> str:
    link = f"{runtime.frontend_url}/reset-password/{uid}/{token}"
    return (
        "Reset your password:\n\n"
        f"{link}\n\n"
        "This link expires in 1 hour. "
        "If you didn't request this, ignore this email."
    )
