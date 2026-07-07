"""Standard API error envelope for CHT and other server-to-server clients.

Matches legacy MediaHub public API shape (chm-mediahub/backend/legacy/main.py):
  { "error": { "code", "message", "status", "request_id" } }
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger("contenthub.api")

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


def _log_public_api_error(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str | None,
) -> None:
    extra = {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "query": request.url.query or None,
        "status_code": status_code,
        "error_code": code,
    }
    if status_code >= 500:
        logger.error("public api error: %s", message, extra=extra)
    elif status_code >= 400:
        logger.warning("public api error: %s", message, extra=extra)


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


def _nestjs_error(status_code: int, message: str) -> JSONResponse:
    labels = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        422: "Unprocessable Entity",
        429: "Too Many Requests",
        500: "Internal Server Error",
    }
    return JSONResponse(
        status_code=status_code,
        content={
            "statusCode": status_code,
            "message": message,
            "error": labels.get(status_code, "Error"),
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    message = _stringify_detail(exc.detail)
    if request.url.path.startswith("/api/public"):
        code = _ERROR_CODE_MAP.get(exc.status_code, f"HTTP_{exc.status_code}")
        req_id = _request_id(request)
        _log_public_api_error(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            request_id=req_id,
        )
        return json_error(exc.status_code, message, request_id=req_id)
    if request.url.path.startswith("/api/admin"):
        return _nestjs_error(exc.status_code, message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    message = format_validation_errors(exc)
    if request.url.path.startswith("/api/public"):
        req_id = _request_id(request)
        _log_public_api_error(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message=message,
            request_id=req_id,
        )
        return json_error(422, message, request_id=req_id)
    if request.url.path.startswith("/api/admin"):
        return _nestjs_error(422, message)
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    if request.url.path.startswith("/api/public"):
        req_id = _request_id(request)
        _log_public_api_error(
            request,
            status_code=429,
            code="RATE_LIMITED",
            message="Rate limit exceeded",
            request_id=req_id,
        )
        return json_error(429, "Rate limit exceeded", request_id=req_id)
    return json_error(429, "Rate limit exceeded", request_id=_request_id(request))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    req_id = _request_id(request)
    logger.exception(
        "unhandled exception",
        extra={
            "request_id": req_id,
            "method": request.method,
            "path": request.url.path,
        },
    )
    if request.url.path.startswith("/api/public"):
        return json_error(
            500,
            "Internal server error",
            code="INTERNAL_ERROR",
            request_id=req_id,
        )
    if request.url.path.startswith("/api/admin"):
        return _nestjs_error(500, "Internal server error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
