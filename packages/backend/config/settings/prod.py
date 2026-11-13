from __future__ import annotations

from config.runtime import runtime
from config.settings.base import *  # noqa: F403

DEBUG = False

TASKS = {
    "default": {"BACKEND": "django_tasks_db.backend.DatabaseBackend"},
}

SECURE_SSL_REDIRECT = runtime.secure_ssl_redirect
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

CSRF_TRUSTED_ORIGINS = runtime.csrf_trusted_origins
CORS_ALLOWED_ORIGINS = runtime.cors_allowed_origins

if runtime.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=runtime.sentry_dsn,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment=runtime.environment,
    )
