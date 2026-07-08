"""Ensure backend/src is on sys.path for flat imports (config, models, …)."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent


def install() -> Path:
    """Insert src/ at the front of sys.path."""
    path = str(_SRC_ROOT)
    if path not in sys.path:
        sys.path.insert(0, path)
    return _SRC_ROOT
