"""Standard API error envelope for CHT and other server-to-server clients.

Matches legacy MediaHub public API shape (chm-mediahub/backend/legacy/main.py):
  { "error": { "code", "message", "status", "request_id" } }
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

_ERROR_CODE_MAP: dict[int, str] = {
    401: "AUTH_INVALID_KEY",
    403: "AUTH_FORBIDDEN",
    404: "RESOURCE_NOT_FOUND",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_body(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code or _ERROR_CODE_MAP.get(status_code, f"HTTP_{status_code}"),
            "message": message,
            "status": status_code,
            "request_id": request_id,
        }
    }


def json_error(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(status_code, message, code=code, request_id=request_id),
    )


def _stringify_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                msg = item.get("msg", "invalid")
                loc = item.get("loc")
                if loc:
                    path = ".".join(str(part) for part in loc if part != "body")
                    parts.append(f"{path}: {msg}" if path else str(msg))
                else:
                    parts.append(str(msg))
            else:
                parts.append(str(item))
        return "; ".join(parts) if parts else "Validation error"
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or detail)
    return str(detail)


def format_validation_errors(exc: RequestValidationError) -> str:
    return _stringify_detail(exc.errors())


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if request.url.path.startswith("/api/public"):
        return json_error(
            exc.status_code,
            _stringify_detail(exc.detail),
            request_id=_request_id(request),
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if request.url.path.startswith("/api/public"):
        return json_error(
            422,
            format_validation_errors(exc),
            request_id=_request_id(request),
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    if request.url.path.startswith("/api/public"):
        return json_error(429, "Rate limit exceeded", request_id=_request_id(request))
    return json_error(429, "Rate limit exceeded", request_id=_request_id(request))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
