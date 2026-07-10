"""Shared runtime helpers for sync Lambda handlers."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Coroutine, TypeVar

_T = TypeVar("_T")


def install_paths() -> None:
    """Put application modules on sys.path (Lambda zip or local repo)."""
    sync_root = Path(__file__).resolve().parent.parent
    candidates = [
        sync_root,
        sync_root.parent / "backend" / "src",
    ]
    for path in candidates:
        entry = str(path)
        if path.is_dir() and entry not in sys.path:
            sys.path.insert(0, entry)
    config_module = sync_root / "config.py"
    if config_module.is_file():
        from shared.secrets import ensure_lambda_secrets

        ensure_lambda_secrets()
        return
    from path_setup import install

    install()


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run an async job coroutine from a sync Lambda handler."""
    return asyncio.run(coro)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON output to stdout.

    Matches the ECS API's structured format (backend/src/logging_config.py)
    so CloudWatch Logs Insights queries can `fields @timestamp, level, name,
    message` uniformly across the whole platform. Falls back to a plain
    formatter if the ECS logging_config module (which ships in the
    sync-lambda zip via the backend/src copy) is not importable — that
    keeps unit tests and local dev functional.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    try:
        from logging_config import CustomJsonFormatter

        handler.setFormatter(
            CustomJsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
    except ImportError:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)
