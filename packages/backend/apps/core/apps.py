from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self) -> None:
        from apps.core.observability.logging import configure_structlog
        from apps.core.observability.otel import setup_opentelemetry
        from apps.core.observability.posthog import configure_posthog
        from config.runtime import runtime

        try:
            configure_structlog()
            configure_posthog(api_key=runtime.posthog_api_key, host=runtime.posthog_host)
            setup_opentelemetry(
                endpoint=runtime.otel_exporter_otlp_endpoint,
                service_name="sukuna-backend",
                environment=runtime.environment,
            )
        except Exception:
            logger.exception("observability_setup_failed")
