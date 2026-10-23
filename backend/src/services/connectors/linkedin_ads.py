"""LinkedIn Ads connector (Marketing API, versioned ``/rest``).

CPR-15: the daily sync reads every ad campaign and creative in the ad
account, then daily analytics per creative. Each creative becomes a post in
the Hub that points to the organic post it promotes (``content.reference``).
LinkedIn keeps daily analytics for six months, so the first run can backfill
that far.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, unquote

import httpx

from services.connectors.common import (
    ConnectorError,
    request_failed,
    response_json,
)

log = logging.getLogger(__name__)

LINKEDIN_REST = "https://api.linkedin.com/rest"
LINKEDIN_INTROSPECT = "https://www.linkedin.com/oauth/v2/introspectToken"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

_PAGE_SIZE = 100
# adAnalytics takes a list of creatives per call; keep URLs short.
_CREATIVES_PER_CALL = 20

# adAnalytics returns only impressions and clicks unless fields are named (max 20).
METRIC_FIELDS = {
    "impressions": "impressions",
    "clicks": "clicks",
    "landingPageClicks": "landing_page_clicks",
    "totalEngagements": "engagements",
    "reactions": "reactions",
    "comments": "comments",
    "shares": "shares",
    "follows": "follows",
    "videoStarts": "video_starts",
    "videoViews": "video_views",
    "videoFirstQuartileCompletions": "video_25",
    "videoMidpointCompletions": "video_50",
    "videoThirdQuartileCompletions": "video_75",
    "videoCompletions": "video_completions",
    "costInLocalCurrency": "cost",
}
_ANALYTICS_FIELDS = ["dateRange", "pivotValues", *METRIC_FIELDS]

# Post URN kinds a creative can promote.
POST_URN_KINDS = ("share", "ugcPost", "activity", "post")


@dataclass(frozen=True)
class AdCampaign:
    id: str
    name: str
    status: str
    type: str


@dataclass(frozen=True)
class Creative:
    urn: str
    campaign_id: str
    name: str
    status: str
    content_type: str
    # The organic post the creative promotes (share / ugcPost URN), if any.
    reference: str | None
    created_at: datetime | None


@dataclass
class CreativeDay:
    creative_urn: str
    day: date
    metrics: dict[str, float] = field(default_factory=dict)


def _linkedin_headers(access_token: str, api_version: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": api_version,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _date_range_param(start: date, end: date) -> str:
    return (
        f"(start:(year:{start.year},month:{start.month},day:{start.day}),"
        f"end:(year:{end.year},month:{end.month},day:{end.day}))"
    )


def _urn_id(urn: str) -> str:
    return urn.rsplit(":", 1)[-1]


def normalize_post_urn(value: str | None) -> str | None:
    """``urn:li:share:1`` / ``ugcPost`` / ``activity`` from a URN or a post URL."""
    if not value:
        return None
    text = unquote(str(value)).strip()
    start = text.find("urn:li:")
    if start < 0:
        return None
    urn = text[start:].split("/")[0].split("?")[0].rstrip(",)")
    parts = urn.split(":")
    if len(parts) != 4 or parts[2] not in POST_URN_KINDS or not parts[3]:
        return None
    return urn


def post_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/"


async def _get_json(
    client: httpx.AsyncClient, url: str, *, access_token: str, api_version: str, what: str
) -> dict[str, Any]:
    try:
        response = await client.get(url, headers=_linkedin_headers(access_token, api_version))
    except httpx.HTTPError as exc:
        raise request_failed(what, exc) from exc
    if response.status_code == 401:
        raise ConnectorError(
            "LinkedIn Ads access token expired or invalid — renew LINKEDIN_ADS_REFRESH_TOKEN"
        )
    if response.status_code >= 400:
        raise ConnectorError(f"{what} error {response.status_code}: {response.text[:500]}")
    return response_json(response, what)


async def _paged(
    client: httpx.AsyncClient, url: str, *, access_token: str, api_version: str, what: str
) -> list[dict[str, Any]]:
    """Follow ``metadata.nextPageToken`` (cursor paging on versioned finders)."""
    elements: list[dict[str, Any]] = []
    page_token = ""
    while True:
        page_url = url + (f"&pageToken={quote(page_token, safe='')}" if page_token else "")
        payload = await _get_json(
            client, page_url, access_token=access_token, api_version=api_version, what=what
        )
        elements.extend(payload.get("elements") or [])
        page_token = (payload.get("metadata") or {}).get("nextPageToken") or ""
        if not page_token:
            return elements


async def list_ad_campaigns(
    *, access_token: str, ad_account_id: str, api_version: str, client: httpx.AsyncClient
) -> list[AdCampaign]:
    elements = await _paged(
        client,
        f"{LINKEDIN_REST}/adAccounts/{ad_account_id}/adCampaigns?q=search&pageSize={_PAGE_SIZE}",
        access_token=access_token,
        api_version=api_version,
        what="LinkedIn adCampaigns",
    )
    return [
        AdCampaign(
            id=str(element.get("id") or ""),
            name=element.get("name") or "",
            status=element.get("status") or "",
            type=element.get("type") or "",
        )
        for element in elements
    ]


def creative_from_element(element: dict[str, Any]) -> Creative:
    """The promoted post is ``content.reference``, or nested in the ad type:
    ``content.videoAd.reference`` (ugcPost), ``standardUpdateAd`` (share),
    ``documentAd`` and so on. Spotlight, follow, text and similar ads promote
    no post.
    """
    content = element.get("content") or {}
    if "reference" in content:
        content_type, reference = "reference", normalize_post_urn(content.get("reference"))
    else:
        content_type = next(iter(content), "unknown")
        nested = content.get(content_type)
        reference = normalize_post_urn(nested.get("reference")) if isinstance(nested, dict) else None
    created = element.get("createdAt")
    return Creative(
        urn=str(element.get("id") or ""),
        campaign_id=_urn_id(str(element.get("campaign") or "")),
        name=element.get("name") or ((content.get("textAd") or {}).get("headline") or ""),
        status=element.get("intendedStatus") or element.get("status") or "",
        content_type=content_type,
        reference=reference,
        created_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else None,
    )


async def list_creatives(
    *, access_token: str, ad_account_id: str, api_version: str, client: httpx.AsyncClient
) -> list[Creative]:
    elements = await _paged(
        client,
        f"{LINKEDIN_REST}/adAccounts/{ad_account_id}/creatives?q=criteria&pageSize={_PAGE_SIZE}",
        access_token=access_token,
        api_version=api_version,
        what="LinkedIn creatives",
    )
    return [creative_from_element(element) for element in elements if element.get("id")]


async def fetch_creative_days(
    *,
    access_token: str,
    creative_urns: list[str],
    start: date,
    end: date,
    api_version: str,
    client: httpx.AsyncClient,
) -> list[CreativeDay]:
    """Daily analytics per creative; days without activity are not returned."""
    days: list[CreativeDay] = []
    for offset in range(0, len(creative_urns), _CREATIVES_PER_CALL):
        chunk = creative_urns[offset : offset + _CREATIVES_PER_CALL]
        encoded = ",".join(quote(urn, safe="") for urn in chunk)
        # Rest.li syntax: List(...) and (start:(...)) stay literal and URNs are
        # encoded once, so the query is built by hand. A params dict would
        # percent-encode it again and LinkedIn would reject the URNs.
        url = (
            f"{LINKEDIN_REST}/adAnalytics?q=analytics&pivot=CREATIVE&timeGranularity=DAILY"
            f"&dateRange={_date_range_param(start, end)}"
            f"&creatives=List({encoded})"
            f"&fields={','.join(_ANALYTICS_FIELDS)}"
        )
        payload = await _get_json(
            client, url, access_token=access_token, api_version=api_version, what="LinkedIn adAnalytics"
        )
        for element in payload.get("elements") or []:
            pivots = element.get("pivotValues") or []
            begin = (element.get("dateRange") or {}).get("start") or {}
            if not pivots or not begin:
                continue
            days.append(
                CreativeDay(
                    creative_urn=str(pivots[0]),
                    day=date(int(begin["year"]), int(begin["month"]), int(begin["day"])),
                    metrics={
                        name: float(element.get(field) or 0)
                        for field, name in METRIC_FIELDS.items()
                    },
                )
            )
    return days


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

