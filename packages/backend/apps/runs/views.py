"""REST endpoints for sandbox callback ingestion."""

from __future__ import annotations

import structlog
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.exceptions import NotFound
from apps.runs.services.callbacks import InvalidCallback, verify_and_ingest
from apps.runs.services.proxy import InvalidProxy, handle_proxy_request

_log = structlog.get_logger(__name__)


@csrf_exempt
@require_POST
def sandbox_callback_view(request: HttpRequest) -> HttpResponse:
    raw_body = request.body
    # Proxied tool / knowledge-search requests share this URL but carry a header
    # signature; callback batches sign in the body. Route by that header.
    signature = request.headers.get("X-Midsphere-Signature")
    if signature:
        return _handle_proxy(raw_body, signature)
    return _handle_callback(raw_body)


def _handle_callback(raw_body: bytes) -> HttpResponse:
    try:
        result = verify_and_ingest(raw_body)
    except InvalidCallback as exc:
        _log.warning("sandbox_callback_rejected", reason=str(exc))
        return HttpResponseBadRequest(str(exc))
    except NotFound as exc:
        _log.warning("sandbox_callback_not_found", reason=str(exc))
        return JsonResponse({"error": str(exc)}, status=404)
    except Exception:
        _log.exception("sandbox_callback_error")
        return JsonResponse({"error": "Internal error."}, status=500)
    return JsonResponse(result, status=200)


def _handle_proxy(raw_body: bytes, signature: str) -> HttpResponse:
    try:
        return JsonResponse(handle_proxy_request(raw_body, signature), status=200)
    except InvalidProxy as exc:
        _log.warning("sandbox_proxy_rejected", reason=str(exc))
        return HttpResponseBadRequest(str(exc))
    except NotFound as exc:
        return JsonResponse({"error": str(exc)}, status=404)
    except Exception:
        _log.exception("sandbox_proxy_error")
        return JsonResponse({"error": "Internal error."}, status=500)
