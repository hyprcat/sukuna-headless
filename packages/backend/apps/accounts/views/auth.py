"""JSON auth endpoints for the Astro SSR dashboard."""

from __future__ import annotations

from typing import cast

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User
from apps.accounts.schemas.config import AuthFlowConfig
from apps.accounts.services import auth_flows
from apps.accounts.services.onboarding import verify_email_and_workspace
from apps.accounts.views.helpers import (
    err,
    json_body,
    ok,
    resolve_uid,
    user_payload,
    user_workspaces,
    workspace_payload,
)
from apps.core.events import record_event


def _invalid_verification_link() -> JsonResponse:
    return err("Invalid or expired verification link.", status=400)


def _login_failed_response(email: str) -> JsonResponse:
    auth_flows.audit_login_failure(email, "invalid_credentials")
    return err("Invalid email or password.", status=401)


def _login_unverified_response(email: str) -> JsonResponse:
    auth_flows.audit_login_failure(email, "email_unverified")
    return err(
        "Verify your email before signing in.",
        field="email",
        status=403,
        email_verification_required=True,
    )


def _login_rate_limited_response(email: str) -> JsonResponse:
    auth_flows.audit_login_failure(email, "rate_limited")
    return err("Too many sign-in attempts. Try again in a few minutes.", status=429)


def _login_success_response(request: HttpRequest, user: User) -> JsonResponse:
    login(request, user)
    record_event(
        "user_logged_in",
        distinct_id=str(user.pk),
        properties={"email": user.email},
    )
    workspaces = user_workspaces(user)
    ws_slug = workspaces[0]["slug"] if workspaces else None
    return ok(user=user_payload(user), workspace_slug=ws_slug, workspaces=workspaces)


def _validate_password_strength(password: str, user: User | None = None) -> JsonResponse | None:
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return err(" ".join(exc.messages), field="password")
    return None


def _validate_signup(email: str, password: str) -> JsonResponse | None:
    if not email:
        return err("Email is required.", field="email")
    if not password:
        return err("Password is required.", field="password")
    if User.objects.filter(email=email).exists():
        return err("An account with this email already exists.", field="email")
    return _validate_password_strength(password)


@csrf_exempt
@require_POST
def signup_view(request: HttpRequest) -> JsonResponse:
    body = json_body(request)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    full_name = (body.get("full_name") or "").strip()

    validation_err = _validate_signup(email, password)
    if validation_err is not None:
        return validation_err

    user = auth_flows.create_unverified_user(email=email, password=password, full_name=full_name)
    return ok(201, user=user_payload(user), email_verification_required=True)


def _login_authenticated_response(
    request: HttpRequest,
    user: User,
    cache_key: str,
    email: str,
) -> JsonResponse:
    auth_flows.clear_login_failures(cache_key)
    if not user.is_email_verified:
        return _login_unverified_response(email)
    return _login_success_response(request, user)


@csrf_exempt
@require_POST
def login_view(request: HttpRequest) -> JsonResponse:
    body = json_body(request)
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return err("Email and password are required.")

    config = AuthFlowConfig()
    cache_key = auth_flows.login_attempt_key(request, email, config)
    if auth_flows.login_rate_limited(cache_key, config):
        return _login_rate_limited_response(email)

    user = authenticate(request, username=email, password=password)
    if user is None:
        auth_flows.record_login_failure(cache_key, config)
        return _login_failed_response(email)

    return _login_authenticated_response(request, user, cache_key, email)


@csrf_exempt
@require_POST
def logout_view(request: HttpRequest) -> JsonResponse:
    user_id = str(request.user.pk) if request.user.is_authenticated else "anonymous"
    logout(request)
    record_event("user_logged_out", distinct_id=user_id)
    return ok()


@csrf_exempt
@require_POST
def verify_email_view(request: HttpRequest) -> JsonResponse:
    body = json_body(request)
    uidb64 = body.get("uid") or ""
    token = body.get("token") or ""

    user = resolve_uid(uidb64)
    if user is None:
        return _invalid_verification_link()

    result = verify_email_and_workspace(user, token)
    if result is None:
        return _invalid_verification_link()

    _verified_user, workspace, already_verified = result
    return ok(already_verified=already_verified, workspace=workspace_payload(workspace))


@csrf_exempt
@require_POST
def forgot_password_view(request: HttpRequest) -> JsonResponse:
    body = json_body(request)
    email = (body.get("email") or "").strip().lower()
    if not email:
        return err("Email is required.", field="email")

    config = AuthFlowConfig()
    cache_key = auth_flows.password_reset_request_key(request, email, config)
    if auth_flows.password_reset_rate_limited(cache_key, config):
        auth_flows.audit_password_reset_request(email, "rate_limited")
        return err("Too many reset requests. Try again in a few minutes.", status=429)

    auth_flows.record_password_reset_request(cache_key, config)
    auth_flows.request_password_reset(email)
    return ok(message="If an account with that email exists, we sent a reset link.")


def _reset_password_validation_error(
    user: User | None,
    token: str,
    new_password: str,
) -> JsonResponse | None:
    if user is None or not auth_flows.password_reset_token_valid(user, token):
        return err("Invalid or expired reset link.", status=400)
    if not new_password:
        return err("Password is required.", field="password")
    return _validate_password_strength(new_password, user=user)


@csrf_exempt
@require_POST
def reset_password_view(request: HttpRequest) -> JsonResponse:
    body = json_body(request)
    uidb64 = body.get("uid") or ""
    token = body.get("token") or ""
    new_password = body.get("password") or ""

    user = resolve_uid(uidb64)
    validation_err = _reset_password_validation_error(user, token, new_password)
    if validation_err is not None:
        return validation_err

    reset_user = auth_flows.complete_password_reset(cast("User", user), token, new_password)
    if reset_user is None:
        return err("Invalid or expired reset link.", status=400)
    return ok()


@csrf_exempt
@require_POST
def resend_verification_view(request: HttpRequest) -> JsonResponse:
    body = json_body(request)
    email = (body.get("email") or "").strip().lower()
    if not email:
        return err("Email is required.", field="email")

    config = AuthFlowConfig()
    cache_key = auth_flows.verification_resend_key(request, email, config)
    if auth_flows.verification_resend_rate_limited(cache_key, config):
        auth_flows.audit_verification_resend(email, "rate_limited")
        return err(
            "Too many verification emails. Try again in a few minutes.",
            status=429,
        )

    auth_flows.record_verification_resend_request(cache_key, config)
    auth_flows.resend_verification(email)
    return ok(message="If your email is unverified, we sent a new verification link.")


@require_GET
def me_view(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return err("Not authenticated.", status=401)
    user = request.user
    workspaces = user_workspaces(user)
    ws_slug = workspaces[0]["slug"] if workspaces else None
    return ok(user=user_payload(user), workspace_slug=ws_slug, workspaces=workspaces)
