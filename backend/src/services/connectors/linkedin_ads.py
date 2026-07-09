"""LinkedIn Ads analytics connector (Marketing API /rest/adAnalytics)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from services.connectors.common import (
    ConnectorError,
    FetchResult,
    campaign_platform_config,
    metric_str,
    reporting_period,
    safe_rate,
)

log = logging.getLogger(__name__)

LINKEDIN_REST = "https://api.linkedin.com/rest"
LINKEDIN_VERSION = "202501"

_ANALYTICS_FIELDS = [
    "impressions",
    "clicks",
    "videoViews",
    "videoCompletions",
    "averageDwellTime",
    "dateRange",
    "pivotValues",
]


def _linkedin_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _campaign_urn(campaign_id: str) -> str:
    value = campaign_id.strip()
    if value.startswith("urn:"):
        return value
    return f"urn:li:sponsoredCampaign:{value}"


def _account_urn(ad_account_id: str) -> str:
    value = ad_account_id.strip()
    if value.startswith("urn:"):
        return value
    return f"urn:li:sponsoredAccount:{value}"


def _date_range_param(start: date, end: date) -> str:
    return (
        f"(start:(year:{start.year},month:{start.month},day:{start.day}),"
        f"end:(year:{end.year},month:{end.month},day:{end.day}))"
    )


def _resolve_campaign_ids(
    integration: dict[str, Any],
    campaign_id: int,
) -> list[str]:
    per_campaign = campaign_platform_config(integration, campaign_id)
    ids = per_campaign.get("linkedinCampaignIds") or integration.get(
        "linkedinCampaignIds"
    )
    if not ids:
        return []
    if isinstance(ids, str):
        return [ids]
    return [str(item) for item in ids]


def _element_label(element: dict[str, Any]) -> str:
    pivot_values = element.get("pivotValues") or []
    if pivot_values:
        urn = str(pivot_values[0])
        if ":" in urn:
            return urn.rsplit(":", 1)[-1]
        return urn
    date_range = element.get("dateRange") or {}
    start = date_range.get("start") or {}
    if start:
        return f"{start.get('year')}-{int(start.get('month') or 0):02d}-{int(start.get('day') or 0):02d}"
    return "aggregate"


def _element_to_row(element: dict[str, Any]) -> dict[str, str]:
    impressions = float(element.get("impressions") or 0)
    clicks = float(element.get("clicks") or 0)
    video_views = float(element.get("videoViews") or 0)
    completions = float(element.get("videoCompletions") or 0)
    dwell = element.get("averageDwellTime")
    dwell_seconds = float(dwell) if dwell is not None else 0.0

    row: dict[str, str] = {
        "campaign": _element_label(element),
        "impressions": metric_str(impressions),
        "clicks": metric_str(clicks),
        "video views": metric_str(video_views),
        "completion rate": safe_rate(completions, video_views),
        "dwell time": metric_str(dwell_seconds),
        "ctr": safe_rate(clicks, impressions),
    }

    date_range = element.get("dateRange") or {}
    start = date_range.get("start") or {}
    if start:
        row["date"] = (
            f"{start.get('year')}-{int(start.get('month', 0)):02d}-"
            f"{int(start.get('day', 0)):02d}"
        )
    return row


async def fetch_linkedin_ads_metrics(
    *,
    access_token: str,
    ad_account_id: str,
    campaign_id: int,
    integration: dict[str, Any],
    reporting_period_start: date | None,
    reporting_period_end: date | None,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    if not access_token:
        raise ConnectorError(
            "LinkedIn Ads access token missing — set LINKEDIN_ADS_ACCESS_TOKEN "
            "or integration accessToken"
        )
    if not ad_account_id:
        raise ConnectorError(
            "LinkedIn ad account missing — set LINKEDIN_AD_ACCOUNT_ID "
            "or integration adAccountId"
        )

    period_start, period_end = reporting_period(
        reporting_period_start, reporting_period_end
    )
    linkedin_campaign_ids = _resolve_campaign_ids(integration, campaign_id)

    params: dict[str, str] = {
        "q": "analytics",
        "pivot": "CAMPAIGN",
        "timeGranularity": "DAILY" if period_start != period_end else "ALL",
        "dateRange": _date_range_param(period_start, period_end),
        "fields": ",".join(_ANALYTICS_FIELDS),
    }

    if linkedin_campaign_ids:
        encoded = ",".join(
            quote(_campaign_urn(cid), safe="") for cid in linkedin_campaign_ids
        )
        params["campaigns"] = f"List({encoded})"
    else:
        encoded_account = quote(_account_urn(ad_account_id), safe="")
        params["accounts"] = f"List({encoded_account})"

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)

    try:
        response = await client.get(
            f"{LINKEDIN_REST}/adAnalytics",
            params=params,
            headers=_linkedin_headers(access_token),
        )
        if response.status_code == 401:
            raise ConnectorError("LinkedIn Ads access token expired or invalid")
        if response.status_code >= 400:
            detail = response.text[:500]
            raise ConnectorError(
                f"LinkedIn Ads API error {response.status_code}: {detail}"
            )

        payload = response.json()
        elements = payload.get("elements") or []
        rows = [_element_to_row(element) for element in elements]
        if not rows:
            raise ConnectorError(
                "LinkedIn Ads returned no analytics rows for the configured "
                "account/campaigns and date range"
            )

        return FetchResult(
            rows=rows,
            raw={
                "connector": "linkedin_ads",
                "adAccountId": ad_account_id,
                "linkedinCampaignIds": linkedin_campaign_ids,
                "periodStart": period_start.isoformat(),
                "periodEnd": period_end.isoformat(),
                "elementCount": len(elements),
                "paging": payload.get("paging"),
            },
        )
    finally:
        if own_client:
            await client.aclose()
