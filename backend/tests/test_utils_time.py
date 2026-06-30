"""Tests for utils.time."""

from __future__ import annotations

from datetime import datetime, timezone

from utils.time import ensure_utc


def test_ensure_utc_none():
    assert ensure_utc(None) is None


def test_ensure_utc_naive():
    naive = datetime(2024, 1, 15, 12, 0, 0)
    result = ensure_utc(naive)
    assert result is not None
    assert result.tzinfo == timezone.utc
    assert result.hour == 12


def test_ensure_utc_aware_unchanged():
    aware = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert ensure_utc(aware) is aware
