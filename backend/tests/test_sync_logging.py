"""Unit tests for sync/shared/runtime.py::configure_logging.

Specifically regression-covers the bug where AWS Lambda's pre-installed
root logger handler was left in place, meaning our JSON formatter never
attached and sync-lambda CloudWatch logs stayed plain-text.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

SYNC_ROOT = Path(__file__).resolve().parents[2] / "sync"
if str(SYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(SYNC_ROOT))

# We also need backend/src on sys.path so `from logging_config import ...`
# resolves — mirrors the sync-lambda zip layout where backend/src is copied in.
BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


class TestConfigureLogging:
    """Verify the JSON formatter gets installed regardless of pre-existing handlers."""

    def _cleanup_root(self) -> None:
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)

    def test_retrofits_preexisting_handler_with_json_formatter(self):
        """Simulate AWS Lambda: a handler exists before our code runs."""
        self._cleanup_root()
        # Simulate the Lambda runtime's pre-installed handler.
        preexisting = logging.StreamHandler()
        preexisting.setFormatter(logging.Formatter("plain %(message)s"))
        logging.getLogger().addHandler(preexisting)
        assert len(logging.getLogger().handlers) == 1

        from shared.runtime import configure_logging

        configure_logging()

        # Same number of handlers (we don't add a new one), but the formatter
        # on the pre-existing handler is now the JSON one.
        assert len(logging.getLogger().handlers) == 1
        formatter = logging.getLogger().handlers[0].formatter
        assert formatter is not None
        # The JSON formatter is either CustomJsonFormatter (real path) or
        # falls back to plain when python-json-logger is absent. Either way
        # it should not still be our fake `plain %(message)s`.
        assert formatter._fmt != "plain %(message)s"

        self._cleanup_root()

    def test_adds_handler_when_none_preexisting(self):
        """Simulate local dev / unit test: no root handlers."""
        self._cleanup_root()
        assert len(logging.getLogger().handlers) == 0

        from shared.runtime import configure_logging

        configure_logging()

        assert len(logging.getLogger().handlers) == 1
        assert isinstance(logging.getLogger().handlers[0], logging.StreamHandler)
        formatter = logging.getLogger().handlers[0].formatter
        assert formatter is not None

        self._cleanup_root()

    def test_respects_level_argument(self):
        self._cleanup_root()
        from shared.runtime import configure_logging

        configure_logging(level="WARNING")
        assert logging.getLogger().level == logging.WARNING

        self._cleanup_root()
