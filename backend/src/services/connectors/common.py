"""Shared connector types and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


class ConnectorError(Exception):
    """Raised when a platform API call fails or credentials are incomplete."""


@dataclass(frozen=True)
class FetchResult:
    rows: list[dict[str, str]]
    raw: dict[str, Any]


def reporting_period(
    start: date | None,
    end: date | None,
    *,
    default_days: int = 30,
) -> tuple[date, date]:
    today = date.today()
    period_end = end or today
    period_start = start or (period_end - timedelta(days=default_days))
    if period_start > period_end:
        raise ConnectorError("reporting period start must be on or before end")
    return period_start, period_end


def campaign_platform_config(
    integration: dict[str, Any],
    campaign_id: int,
) -> dict[str, Any]:
    """Per-campaign overrides from integration.campaignMap[hubCampaignId]."""
    campaign_map = integration.get("campaignMap") or {}
    entry = campaign_map.get(str(campaign_id)) or campaign_map.get(campaign_id)
    return entry if isinstance(entry, dict) else {}


def metric_str(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def safe_rate(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        return "0"
    return f"{numerator / denominator:.4g}"
