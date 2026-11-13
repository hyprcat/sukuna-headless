from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from strawberry.django.views import GraphQLView as _SyncGraphQLView

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


class GraphQLView(_SyncGraphQLView):
    def get_context(self, request: HttpRequest, response: HttpResponse) -> Any:
        ctx: Any = super().get_context(request, response)
        ctx.principal = getattr(request, "principal", None)
        ctx.workspace = getattr(request, "workspace", None)
        return ctx


def healthz(request: HttpRequest) -> JsonResponse:
    checks: dict[str, bool] = {}

    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        checks["database"] = False

    try:
        cache.set("_healthz", "ok", timeout=5)
        checks["cache"] = cache.get("_healthz") == "ok"
    except Exception:
        checks["cache"] = False

    healthy = all(checks.values())
    status = 200 if healthy else 503
    body = {"status": "ok" if healthy else "degraded", "checks": checks}
    return JsonResponse(body, status=status)


def readyz(request: HttpRequest) -> JsonResponse:
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ready"})
    except Exception:
        return JsonResponse({"status": "not_ready"}, status=503)
