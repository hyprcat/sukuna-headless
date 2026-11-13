from __future__ import annotations

from typing import TYPE_CHECKING

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

if TYPE_CHECKING:
    from sentry_sdk.integrations import Integration


def setup_sentry(
    *,
    dsn: str | None,
    environment: str,
    release: str | None = None,
) -> None:
    """Initialize Sentry. No-op when DSN is unset."""
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        integrations=_sentry_integrations(),
        traces_sample_rate=_traces_sample_rate(environment),
        send_default_pii=False,
        attach_stacktrace=True,
        max_breadcrumbs=50,
    )


def _sentry_integrations() -> list[Integration]:
    return [DjangoIntegration()]


def _traces_sample_rate(environment: str) -> float:
    return 0.1 if environment == "prod" else 1.0
