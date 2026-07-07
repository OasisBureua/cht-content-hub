"""contenthub-api — producer API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from path_setup import install

install()

from logging_config import configure_logging

configure_logging()

from config import get_settings  # noqa: E402
from database import engine  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from errors import register_error_handlers  # noqa: E402
from health.router import router as health_router  # noqa: E402
from public.limits import limiter  # noqa: E402
from admin.router import router as admin_router  # noqa: E402
from public.router import router as public_router  # noqa: E402
from request_logger import RequestLoggerMiddleware  # noqa: E402
from slowapi.middleware import SlowAPIMiddleware  # noqa: E402

settings = get_settings()
logger = logging.getLogger("contenthub-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "contenthub-api ready",
        extra={"service": "contenthub-api", "environment": settings.environment},
    )
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="Producer API — public KOL network (Step 3)",
    version=settings.app_version,
    lifespan=lifespan,
)

app.state.limiter = limiter
register_error_handlers(app)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestLoggerMiddleware)
app.include_router(health_router)
app.include_router(public_router)
app.include_router(admin_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Landing page for bare hostname hits (browser, scanners, misconfigured clients)."""
    return {
        "service": "contenthub-api",
        "status": "ok",
        "health": "/health",
        "public_api": "/api/public/kols",
        "admin_api": "/api/admin/campaigns",
        "admin_docs": "/docs#/admin-campaigns",
        "docs": "/docs",
    }


__all__ = ["app"]
