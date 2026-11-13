from __future__ import annotations


def setup_opentelemetry(
    *,
    endpoint: str | None,
    service_name: str,
    environment: str,
) -> None:
    """Wire Django + psycopg + redis + httpx tracing through an OTLP exporter.

    Skipped when ``endpoint`` is unset — the instrumentations carry overhead we
    don't want in dev / tests with no collector to receive the spans. Imports
    are deferred so the OTel dependency tree stays out of the dev hot path.
    """
    if not endpoint:
        return
    _configure_tracer_provider(
        endpoint=endpoint,
        service_name=service_name,
        environment=environment,
    )
    _instrument_libraries()


def _configure_tracer_provider(*, endpoint: str, service_name: str, environment: str) -> None:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {"service.name": service_name, "deployment.environment": environment}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


def _instrument_libraries() -> None:
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    DjangoInstrumentor().instrument()
    PsycopgInstrumentor().instrument(enable_commenter=True)
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
