"""Shared connector types and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx


class ConnectorError(Exception):
    """Raised when a platform API call fails or credentials are incomplete."""


class ConnectorNotMapped(ConnectorError):
    """The campaign has no campaignMap entry for this platform (CPR-15).

    Connectors never fall back to the whole channel or ad account.
    """


class ConnectorNoData(ConnectorError):
    """The mapped videos or ad campaigns returned nothing for the period."""


@dataclass(frozen=True)
class FetchResult:
    rows: list[dict[str, str]]
    raw: dict[str, Any]


def response_json(response: httpx.Response, service: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ConnectorError(f"{service} returned invalid JSON") from exc


def request_failed(service: str, exc: httpx.HTTPError) -> ConnectorError:
    # Class name only: httpx messages can carry the URL (YouTube's has the key).
    return ConnectorError(f"{service} request failed ({type(exc).__name__})")


def integration_or_env(
    integration: dict[str, Any],
    *,
    integration_key: str,
    env_value: str,
) -> str:
    value = integration.get(integration_key)
    if value is not None and str(value).strip():
        return str(value).strip()
    return env_value.strip()


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


def mapped_ids(integration: dict[str, Any], campaign_id: int, key: str) -> list[str]:
    """IDs from integration.campaignMap[campaign][key]. Global keys are ignored."""
    ids = campaign_platform_config(integration, campaign_id).get(key)
    if not ids:
        return []
    if isinstance(ids, str):
        ids = [ids]
    return [str(item).strip() for item in ids if str(item).strip()]


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
