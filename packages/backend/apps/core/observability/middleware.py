from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse


class StructlogContextMiddleware:
    """Bind per-request context vars (workspace_id / end_user_id / run_id).

    These keys are read off the request by upstream auth/scoping middleware
    and stamped onto every log record emitted during the request. We clear on
    entry to avoid leaking context across requests on reused threads.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = self._request_id(request)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            **{k: v for k, v in self._extract(request, request_id).items() if v is not None}
        )
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    @staticmethod
    def _request_id(request: HttpRequest) -> str:
        return request.headers.get("X-Request-ID") or uuid4().hex

    @staticmethod
    def _extract(request: HttpRequest, request_id: str) -> dict[str, object | None]:
        return {
            "request_id": request_id,
            "workspace_id": getattr(request, "workspace_id", None),
            "end_user_id": getattr(request, "end_user_id", None),
            "run_id": getattr(request, "run_id", None),
            "request_path": request.path,
            "request_method": request.method,
        }
