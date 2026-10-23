"""LinkedIn Ads analytics connector (Marketing API /rest/adAnalytics).

CPR-15: only the ad campaigns mapped to the Hub campaign
(``campaignMap[hubCampaignId].linkedinCampaignIds``) are read; there is no
account-wide fallback. Performance data is kept by LinkedIn for ten years
(daily detail for six months), so a mapped campaign can be backfilled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from config import DEFAULT_LINKEDIN_VERSION
from services.connectors.common import (
    ConnectorError,
    ConnectorNoData,
    ConnectorNotMapped,
    FetchResult,
    mapped_ids,
    metric_str,
    reporting_period,
    request_failed,
    response_json,
    safe_rate,
)

log = logging.getLogger(__name__)

LINKEDIN_REST = "https://api.linkedin.com/rest"
LINKEDIN_INTROSPECT = "https://www.linkedin.com/oauth/v2/introspectToken"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

# adAnalytics returns only impressions and clicks unless fields are named (max 20).
_ANALYTICS_FIELDS = [
    "dateRange",
    "pivotValues",
    "impressions",
    "clicks",
    "landingPageClicks",
    "totalEngagements",
    "reactions",
    "comments",
    "shares",
    "follows",
    "videoStarts",
    "videoViews",
    "videoCompletions",
    "averageDwellTime",
    "costInLocalCurrency",
]

# (row key, element field) for plain counts.
_COUNTS = [
    ("impressions", "impressions"),
    ("clicks", "clicks"),
    ("landing page clicks", "landingPageClicks"),
    ("engagements", "totalEngagements"),
    ("reactions", "reactions"),
    ("comments", "comments"),
    ("shares", "shares"),
    ("follows", "follows"),
    ("video starts", "videoStarts"),
    ("video views", "videoViews"),
]


def _linkedin_headers(access_token: str, api_version: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": api_version,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _campaign_urn(campaign_id: str) -> str:
    value = campaign_id.strip()
    if value.startswith("urn:"):
        return value
    return f"urn:li:sponsoredCampaign:{value}"


def _date_range_param(start: date, end: date) -> str:
    return (
        f"(start:(year:{start.year},month:{start.month},day:{start.day}),"
        f"end:(year:{end.year},month:{end.month},day:{end.day}))"
    )


def _element_label(element: dict[str, Any]) -> str:
    pivot_values = element.get("pivotValues") or []
    if pivot_values:
        urn = str(pivot_values[0])
        if ":" in urn:
            return urn.rsplit(":", 1)[-1]
        return urn
    return "aggregate"


def _element_to_row(element: dict[str, Any]) -> dict[str, str]:
    impressions = float(element.get("impressions") or 0)
    clicks = float(element.get("clicks") or 0)
    video_views = float(element.get("videoViews") or 0)
    completions = float(element.get("videoCompletions") or 0)

    row: dict[str, str] = {"campaign": _element_label(element)}
    for key, field in _COUNTS:
        row[key] = metric_str(float(element.get(field) or 0))
    row["completion rate"] = safe_rate(completions, video_views)
    row["ctr"] = safe_rate(clicks, impressions)
    row["dwell time"] = metric_str(float(element.get("averageDwellTime") or 0))
    row["cost"] = f"{float(element.get('costInLocalCurrency') or 0):.2f}"

    start = (element.get("dateRange") or {}).get("start") or {}
    if start:
        row["date"] = (
            f"{start.get('year')}-{int(start.get('month', 0)):02d}-"
            f"{int(start.get('day', 0)):02d}"
        )
    return row


def mapped_linkedin_campaign_ids(integration: dict[str, Any], campaign_id: int) -> list[str]:
    linkedin_campaign_ids = mapped_ids(integration, campaign_id, "linkedinCampaignIds")
    if not linkedin_campaign_ids:
        raise ConnectorNotMapped(
            f"No LinkedIn ad campaigns mapped to campaign {campaign_id} "
            "(campaignMap.linkedinCampaignIds)"
        )
    return linkedin_campaign_ids


async def fetch_linkedin_ads_metrics(
    *,
    access_token: str,
    ad_account_id: str,
    campaign_id: int,
    integration: dict[str, Any],
    reporting_period_start: date | None,
    reporting_period_end: date | None,
    api_version: str = DEFAULT_LINKEDIN_VERSION,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    if not access_token:
        raise ConnectorError(
            "LinkedIn Ads access token missing — set LINKEDIN_ADS_ACCESS_TOKEN "
            "or integration accessToken"
        )
    linkedin_campaign_ids = mapped_linkedin_campaign_ids(integration, campaign_id)

    period_start, period_end = reporting_period(
        reporting_period_start, reporting_period_end
    )
    encoded = ",".join(quote(_campaign_urn(cid), safe="") for cid in linkedin_campaign_ids)
    granularity = "DAILY" if period_start != period_end else "ALL"
    # Rest.li syntax: List(...) and (start:(...)) stay literal and URNs are
    # encoded once, so the query is built by hand. A params dict would
    # percent-encode it again and LinkedIn would reject the URNs.
    url = (
        f"{LINKEDIN_REST}/adAnalytics?q=analytics&pivot=CAMPAIGN"
        f"&timeGranularity={granularity}"
        f"&dateRange={_date_range_param(period_start, period_end)}"
        f"&campaigns=List({encoded})"
        f"&fields={','.join(_ANALYTICS_FIELDS)}"
    )

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)

    try:
        response = await client.get(url, headers=_linkedin_headers(access_token, api_version))
    except httpx.HTTPError as exc:
        raise request_failed("LinkedIn Ads", exc) from exc
    finally:
        if own_client:
            await client.aclose()

    if response.status_code == 401:
        raise ConnectorError(
            "LinkedIn Ads access token expired or invalid — generate a new token "
            "and update LINKEDIN_ADS_ACCESS_TOKEN"
        )
    if response.status_code >= 400:
        raise ConnectorError(
            f"LinkedIn Ads API error {response.status_code}: {response.text[:500]}"
        )

    payload = response_json(response, "LinkedIn Ads")
    elements = payload.get("elements") or []
    rows = [_element_to_row(element) for element in elements]
    if not rows:
        raise ConnectorNoData(
            "LinkedIn Ads returned no activity for the mapped campaigns in this period"
        )

    return FetchResult(
        rows=rows,
        raw={
            "connector": "linkedin_ads",
            "apiVersion": api_version,
            "adAccountId": ad_account_id,
            "linkedinCampaignIds": linkedin_campaign_ids,
            "periodStart": period_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "elementCount": len(elements),
        },
    )


async def linkedin_token_expires_at(
    *,
    access_token: str,
    client_id: str,
    client_secret: str,
    client: httpx.AsyncClient | None = None,
) -> datetime | None:
    """When the access token expires, from LinkedIn's token introspection.

    Returns None when it can't be determined (missing app credentials, or an
    inactive token).
    """
    if not (access_token and client_id and client_secret):
        return None

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(
            LINKEDIN_INTROSPECT,
            data={"client_id": client_id, "client_secret": client_secret, "token": access_token},
        )
    except httpx.HTTPError as exc:
        raise request_failed("LinkedIn token introspection", exc) from exc
    finally:
        if own_client:
            await client.aclose()

    if response.status_code >= 400:
        raise ConnectorError(f"LinkedIn token introspection failed {response.status_code}")
    body = response_json(response, "LinkedIn token introspection")
    expires_at = body.get("expires_at")
    if not body.get("active") or not expires_at:
        return None
    return datetime.fromtimestamp(int(expires_at), tz=timezone.utc)


@dataclass(frozen=True)
class LinkedInAccessToken:
    access_token: str
    expires_at: datetime
    refresh_expires_at: datetime | None


async def refresh_linkedin_access_token(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    client: httpx.AsyncClient | None = None,
) -> LinkedInAccessToken:
    """Trade the refresh token for a new access token (about 60 days).

    LinkedIn keeps the same refresh token (about a year) until it expires.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    except httpx.HTTPError as exc:
        raise request_failed("LinkedIn token refresh", exc) from exc
    finally:
        if own_client:
            await client.aclose()

    if response.status_code in (400, 401):
        raise ConnectorError(
            "LinkedIn Ads refresh token expired or revoked — generate new tokens "
            "and update LINKEDIN_ADS_REFRESH_TOKEN"
        )
    if response.status_code >= 400:
        raise ConnectorError(f"LinkedIn token refresh failed {response.status_code}")
    body = response_json(response, "LinkedIn token refresh")
    now = datetime.now(timezone.utc)
    refresh_expires_in = body.get("refresh_token_expires_in")
    return LinkedInAccessToken(
        access_token=body["access_token"],
        expires_at=now + timedelta(seconds=int(body.get("expires_in") or 0)),
        refresh_expires_at=(
            now + timedelta(seconds=int(refresh_expires_in)) if refresh_expires_in else None
        ),
    )

