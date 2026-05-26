import logging
import time
import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_context import (
    clear_log_context,
    log_context,
    log_extra,
    update_log_context,
)

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id

        clear_log_context()
        with log_context(
            request_id=request_id,
            correlation_id=correlation_id,
            http_method=request.method,
            http_path=request.url.path,
        ):
            start = time.perf_counter()
            client_host = request.client.host if request.client else None
            logger.info(
                "HTTP request started",
                extra=log_extra(
                    event="http.request.started",
                    client_host=client_host,
                ),
            )

            try:
                response = await call_next(request)
            except Exception:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.exception(
                    "HTTP request failed",
                    extra=log_extra(
                        event="http.request.failed",
                        duration_ms=round(duration_ms, 2),
                    ),
                )
                raise

            duration_ms = (time.perf_counter() - start) * 1000
            update_log_context(http_status=response.status_code)
            log_level = logging.INFO
            if response.status_code >= 500:
                log_level = logging.ERROR
            elif response.status_code >= 400:
                log_level = logging.WARNING

            logger.log(
                log_level,
                "HTTP request completed",
                extra=log_extra(
                    event="http.request.completed",
                    http_status=response.status_code,
                    duration_ms=round(duration_ms, 2),
                ),
            )

            response.headers[REQUEST_ID_HEADER] = request_id
            if CORRELATION_ID_HEADER not in request.headers:
                response.headers[CORRELATION_ID_HEADER] = correlation_id
            return response
