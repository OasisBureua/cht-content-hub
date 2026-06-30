"""Database configuration and session management."""

import logging
import os
import time

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool

from config import get_settings

settings = get_settings()
_db_logger = logging.getLogger("contenthub.db")
_SLOW_QUERY_MS = 500

_is_serverless = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME")) or (
    os.environ.get("CONTENTHUB_SERVICE_ROLE") == "sync-lambda"
)

_engine_kwargs: dict = {
    "echo": False,
    "pool_pre_ping": True,
    "pool_size": settings.db_pool_size,
    "max_overflow": settings.db_max_overflow,
    "pool_timeout": settings.db_pool_timeout,
    "pool_recycle": settings.db_pool_recycle,
}

if _is_serverless:
    _engine_kwargs = {
        "echo": False,
        "poolclass": NullPool,
        "pool_pre_ping": True,
    }

# NullPool is used for some serverless/test URLs; skip sizing kwargs in that case.
if settings.database_url.startswith("sqlite") or "+aiosqlite" in settings.database_url:
    _engine_kwargs = {
        "echo": False,
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }

engine = create_async_engine(settings.database_url, **_engine_kwargs)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info["query_start_time"] = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = conn.info.pop("query_start_time", None)
    if start is not None:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > _SLOW_QUERY_MS:
            _db_logger.warning(
                "SLOW_QUERY duration_ms=%.1f statement=%s",
                elapsed_ms,
                statement[:300],
            )


async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async_session = async_session_maker


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def pool_status() -> dict:
    """Return connection pool stats for health checks."""
    pool = engine.pool
    name = pool.__class__.__name__
    if name == "NullPool":
        return {"pool": "NullPool"}
    status: dict = {"pool": name}
    for key, method in (
        ("pool_size", "size"),
        ("checked_in", "checkedin"),
        ("checked_out", "checkedout"),
        ("overflow", "overflow"),
    ):
        fn = getattr(pool, method, None)
        if callable(fn):
            try:
                status[key] = fn()
            except Exception:
                pass
    return status


async def get_db() -> AsyncSession:
    """Dependency that yields database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
