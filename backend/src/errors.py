"""Standard API error envelope for CHT and other server-to-server clients."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded


def error_body(status_code: int, details: str) -> dict[str, Any]:
    return {"errors": {"status_code": status_code, "details": details}}


def json_error(status_code: int, details: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(status_code, details))


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
        return "; ".join(parts) if parts else "Request validation failed"
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or detail)
    return str(detail)


def format_validation_errors(exc: RequestValidationError) -> str:
    return _stringify_detail(exc.errors())


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return json_error(exc.status_code, _stringify_detail(exc.detail))


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return json_error(422, format_validation_errors(exc))


async def rate_limit_exception_handler(
    _request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    return json_error(429, "Rate limit exceeded")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
