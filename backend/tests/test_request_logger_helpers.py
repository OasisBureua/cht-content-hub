"""Tests for request_logger helpers."""

from __future__ import annotations

from request_logger import access_log_level, sanitize_query


def test_sanitize_query_redacts_sensitive_keys():
    raw = "region=texas&api_key=secret&limit=10"
    assert sanitize_query(raw) == "region=texas&api_key=%5BREDACTED%5D&limit=10"


def test_sanitize_query_empty():
    assert sanitize_query("") is None
    assert sanitize_query(None) is None


def test_access_log_level():
    assert access_log_level(200) == 20  # INFO
    assert access_log_level(404) == 30  # WARNING
    assert access_log_level(500) == 40  # ERROR
