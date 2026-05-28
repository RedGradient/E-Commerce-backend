import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability.metrics import record_http_request

_METRICS_PATHS = frozenset({"/metrics"})


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in _METRICS_PATHS:
            return await call_next(request)

        method = request.method
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            record_http_request(
                method=method,
                path=_normalize_path(request),
                status_code=500,
                duration_seconds=duration,
            )
            raise

        duration = time.perf_counter() - start
        record_http_request(
            method=method,
            path=_normalize_path(request),
            status_code=response.status_code,
            duration_seconds=duration,
        )
        return response


def _normalize_path(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None:
        return route.path
    return request.url.path
