"""Request logging middleware with request ID tracing."""

from __future__ import annotations

import logging
import time
import uuid
from urllib.parse import parse_qsl, urlencode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("contenthub.access")

# ALB/ECS probes and OpenAPI static assets — skip high-frequency noise.
_SKIP_PATHS = {
    "/health",
    "/health/live",
    "/health/ready",
    "/docs",
    "/openapi.json",
    "/redoc",
}

_SENSITIVE_QUERY_KEYS = frozenset(
    {"api_key", "key", "token", "password", "secret", "authorization"}
)


def sanitize_query(query: str | None) -> str | None:
    if not query:
        return None
    pairs = parse_qsl(query, keep_blank_values=True)
    redacted = [
        (key, "[REDACTED]" if key.lower() in _SENSITIVE_QUERY_KEYS else value)
        for key, value in pairs
    ]
    return urlencode(redacted) or None


def access_log_level(status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    return logging.INFO


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Request-Id"] = request_id

        if request.url.path in _SKIP_PATHS:
            return response

        extra = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": sanitize_query(request.url.query),
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 1),
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }
        route = request.scope.get("route")
        if route is not None and getattr(route, "path", None):
            extra["route"] = route.path

        logger.log(
            access_log_level(response.status_code),
            "request complete",
            extra=extra,
        )

        return response
