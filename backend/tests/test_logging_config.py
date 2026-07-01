"""Tests for JSON logging configuration."""

from __future__ import annotations

import json
import logging
import sys

from logging_config import CustomJsonFormatter


def test_json_formatter_emits_cht_style_fields():
    formatter = CustomJsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    record = logging.LogRecord(
        name="contenthub.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request complete",
        args=(),
        exc_info=None,
    )
    record.request_id = "abc-123"
    record.method = "GET"
    record.path = "/api/public/kols"
    record.status_code = 200

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "request complete"
    assert payload["name"] == "contenthub.access"
    assert payload["logger"] == "contenthub.access"
    assert payload["levelname"] == "INFO"
    assert payload["level"] == "INFO"
    assert "asctime" in payload
    assert payload["request_id"] == "abc-123"
    assert payload["method"] == "GET"


def test_formatter_includes_traceback_on_exception():
    formatter = CustomJsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="contenthub-api",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="failed",
        args=(),
        exc_info=exc_info,
    )
    payload = json.loads(formatter.format(record))
    assert "traceback" in payload
    assert "ValueError: boom" in payload["traceback"]
