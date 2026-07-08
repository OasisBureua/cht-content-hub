"""Structured JSON logging (CHT worker / platform pattern)."""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter


class CustomJsonFormatter(JsonFormatter):
    """JSON formatter with logger/level fields and exception tracebacks."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["logger"] = record.name
        log_record["level"] = record.levelname
        if record.exc_info:
            log_record["traceback"] = self.formatException(record.exc_info)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON output to stdout (CloudWatch-friendly)."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        CustomJsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Return a named logger (inherits root JSON handler)."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger
