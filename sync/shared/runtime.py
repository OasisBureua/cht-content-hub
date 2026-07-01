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


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
