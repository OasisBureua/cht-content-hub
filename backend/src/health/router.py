"""Health and actuator endpoints (CHT platform pattern)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from config import get_settings
from database import async_session_maker, pool_status

router = APIRouter(tags=["Health"])

_START_TIME = time.monotonic()
_DB_READY_TIMEOUT_SEC = 5.0


def _uptime_seconds() -> int:
    return int(time.monotonic() - _START_TIME)


async def _database_check() -> dict[str, Any]:
    try:
        async with async_session_maker() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "up", "message": "Database connection is healthy", **pool_status()}
    except Exception as exc:
        return {"status": "down", "message": str(exc), **pool_status()}


async def _database_check_with_timeout() -> dict[str, Any]:
    try:
        result = await asyncio.wait_for(_database_check(), timeout=_DB_READY_TIMEOUT_SEC)
    except TimeoutError:
        return {
            "status": "up",
            "message": "degraded (check timed out)",
            "degraded": True,
            **pool_status(),
        }
    if result.get("status") == "down":
        return {
            "status": "up",
            "message": f"degraded ({result.get('message', 'database unavailable')})",
            "degraded": True,
            **pool_status(),
        }
    return result


@router.get("/health")
async def health() -> dict[str, Any]:
    """Basic health — ALB target check (app up, no DB)."""
    return {
        "status": "ok",
        "info": {"app": {"status": "up"}},
        "details": {"app": {"status": "up"}},
    }


@router.get("/health/ready")
async def health_ready() -> dict[str, Any]:
    """Readiness — DB check with timeout; always 200 (degraded if DB slow/down)."""
    db = await _database_check_with_timeout()
    return {
        "status": "ok",
        "info": {"database": db},
        "details": {"database": db},
    }


@router.get("/health/live")
async def health_live() -> dict[str, Any]:
    """Liveness — process is running."""
    return {
        "status": "ok",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uptime": _uptime_seconds(),
    }


@router.get("/health/detail")
async def health_detail() -> dict[str, Any]:
    """Detailed component health."""
    settings = get_settings()
    db = await _database_check()
    return {
        "status": "ok" if db.get("status") == "up" else "error",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "components": {"database": db},
        "application": {
            "version": settings.app_version,
            "uptime": _uptime_seconds(),
            "environment": settings.environment,
            "service": settings.service_role,
        },
    }


@router.get("/actuator/info")
async def actuator_info() -> dict[str, Any]:
    """Deployment metadata for ops / DR verification."""
    settings = get_settings()
    return {
        "app-name": settings.app_name,
        "env": settings.environment,
        "region": settings.aws_region,
        "image-tag": settings.app_version,
        "service-role": settings.service_role,
        "uptime-seconds": _uptime_seconds(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "build": {
            "image": settings.container_image or None,
        },
    }
