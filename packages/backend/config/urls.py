from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.decorators.csrf import csrf_exempt

from apps.accounts.views.auth import (
    forgot_password_view,
    login_view,
    logout_view,
    me_view,
    resend_verification_view,
    reset_password_view,
    signup_view,
    verify_email_view,
)
from apps.billing.services.webhooks import dodo_webhook_view
from apps.runs.views import sandbox_callback_view
from config.schema import schema
from config.views import GraphQLView, healthz, readyz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql/", csrf_exempt(GraphQLView.as_view(schema=schema))),
    path("auth/signup/", signup_view),
    path("auth/login/", login_view),
    path("auth/logout/", logout_view),
    path("auth/verify-email/", verify_email_view),
    path("auth/forgot-password/", forgot_password_view),
    path("auth/reset-password/", reset_password_view),
    path("auth/resend-verification/", resend_verification_view),
    path("auth/me/", me_view),
    path("webhooks/dodo/", dodo_webhook_view),
    path("webhooks/sandbox/callbacks", sandbox_callback_view),
    path("healthz", healthz),
    path("readyz", readyz),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls)), *urlpatterns]
