"""Parallel read-only DB helpers (Postgres uses separate sessions)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import async_session_maker

T = TypeVar("T")


def uses_sqlite() -> bool:
    return get_settings().database_url.startswith("sqlite")


async def run_read(
    fn: Callable[[AsyncSession], Awaitable[T]], db: AsyncSession | None = None
) -> T:
    if db is not None and uses_sqlite():
        return await fn(db)
    async with async_session_maker() as session:
        return await fn(session)


async def gather_reads(
    db: AsyncSession, *fns: Callable[[AsyncSession], Awaitable[Any]]
) -> list[Any]:
    if uses_sqlite():
        return [await fn(db) for fn in fns]
    return list(await asyncio.gather(*(run_read(fn) for fn in fns)))
