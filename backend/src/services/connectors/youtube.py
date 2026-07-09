"""YouTube channel video metrics connector (Data API v3)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import httpx

from services.connectors.common import (    ConnectorError,
    FetchResult,
    campaign_platform_config,
    metric_str,
    reporting_period,
)

log = logging.getLogger(__name__)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
_ISO_DURATION = re.compile(
    r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
    re.IGNORECASE,
)


def _parse_iso_duration(duration: str) -> str:
    if not duration:
        return ""
    match = _ISO_DURATION.fullmatch(duration.strip())
    if not match:
        return duration
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _published_on_day(published_at: str, day: date) -> bool:
    try:
        when = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return when.astimezone(timezone.utc).date() == day


def _in_period(published_at: str, start: date, end: date) -> bool:
    try:
        when = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    day = when.astimezone(timezone.utc).date()
    return start <= day <= end


def _resolve_video_ids(
    integration: dict[str, Any],
    campaign_id: int,
) -> list[str]:
    per_campaign = campaign_platform_config(integration, campaign_id)
    ids = per_campaign.get("youtubeVideoIds") or integration.get("youtubeVideoIds")
    if not ids:
        return []
    if isinstance(ids, str):
        return [ids]
    return [str(item) for item in ids]


async def _resolve_channel_id(
    *,
    api_key: str,
    channel_id: str,
    channel_handle: str,
    client: httpx.AsyncClient,
) -> str:
    if channel_id:
        return channel_id

    handle = channel_handle.lstrip("@").strip()
    if not handle:
        raise ConnectorError(
            "YouTube channel missing — set YOUTUBE_CHANNEL_ID or "
            "YOUTUBE_CHANNEL_HANDLE (or integration channelId / channelHandle)"
        )

    response = await client.get(
        f"{YOUTUBE_API}/channels",
        params={
            "part": "id",
            "forHandle": handle,
            "key": api_key,
        },
    )
    if response.status_code >= 400:
        raise ConnectorError(
            f"YouTube channel lookup failed {response.status_code}: {response.text[:300]}"
        )
    items = response.json().get("items") or []
    if not items:
        raise ConnectorError(f"YouTube channel @{handle} not found")
    return items[0]["id"]


async def _uploads_playlist_id(
    *, api_key: str, channel_id: str, client: httpx.AsyncClient
) -> str:
    response = await client.get(
        f"{YOUTUBE_API}/channels",
        params={"part": "contentDetails", "id": channel_id, "key": api_key},
    )
    if response.status_code >= 400:
        raise ConnectorError(
            f"YouTube channel details failed {response.status_code}: {response.text[:300]}"
        )
    items = response.json().get("items") or []
    if not items:
        raise ConnectorError(f"YouTube channel {channel_id} not found")
    playlist_id = (
        items[0].get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )
    if not playlist_id:
        raise ConnectorError(f"YouTube channel {channel_id} has no uploads playlist")
    return playlist_id


async def _list_playlist_videos(
    *,
    api_key: str,
    playlist_id: str,
    client: httpx.AsyncClient,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    page_token: str | None = None
    while True:
        response = await client.get(
            f"{YOUTUBE_API}/playlistItems",
            params={
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": 50,
                "pageToken": page_token or "",
                "key": api_key,
            },
        )
        if response.status_code >= 400:
            raise ConnectorError(
                f"YouTube playlistItems failed {response.status_code}: {response.text[:300]}"
            )
        payload = response.json()
        for entry in payload.get("items") or []:
            snippet = entry.get("snippet") or {}
            video_id = (snippet.get("resourceId") or {}).get("videoId")
            if not video_id:
                continue
            items.append(
                {
                    "videoId": video_id,
                    "title": snippet.get("title") or "",
                    "publishedAt": snippet.get("publishedAt") or "",
                }
            )
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return items


async def _video_details(
    *, api_key: str, video_ids: list[str], client: httpx.AsyncClient
) -> list[dict[str, Any]]:
    if not video_ids:
        return []
    details: list[dict[str, Any]] = []
    for offset in range(0, len(video_ids), 50):
        chunk = video_ids[offset : offset + 50]
        response = await client.get(
            f"{YOUTUBE_API}/videos",
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(chunk),
                "key": api_key,
            },
        )
        if response.status_code >= 400:
            raise ConnectorError(
                f"YouTube videos.list failed {response.status_code}: {response.text[:300]}"
            )
        details.extend(response.json().get("items") or [])
    return details


def _video_to_row(item: dict[str, Any]) -> dict[str, str]:
    snippet = item.get("snippet") or {}
    statistics = item.get("statistics") or {}
    content = item.get("contentDetails") or {}
    views = int(statistics.get("viewCount") or 0)
    duration = _parse_iso_duration(content.get("duration") or "")
    return {
        "video id": item.get("id") or "",
        "title": snippet.get("title") or "",
        "published": snippet.get("publishedAt") or "",
        "views": metric_str(views),
        "average view duration": duration,
    }


async def fetch_youtube_metrics(
    *,
    api_key: str,
    channel_id: str,
    channel_handle: str,
    campaign_id: int,
    integration: dict[str, Any],
    reporting_period_start: date | None,
    reporting_period_end: date | None,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    if not api_key:
        raise ConnectorError(
            "YouTube API key missing — set YOUTUBE_API_KEY or integration apiKey"
        )

    period_start, period_end = reporting_period(
        reporting_period_start, reporting_period_end
    )
    explicit_video_ids = _resolve_video_ids(integration, campaign_id)

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0)

    try:
        resolved_channel_id = await _resolve_channel_id(
            api_key=api_key,
            channel_id=channel_id,
            channel_handle=channel_handle,
            client=client,
        )

        if explicit_video_ids:
            video_ids = explicit_video_ids
            playlist_items = [
                {"videoId": vid, "title": "", "publishedAt": ""} for vid in video_ids
            ]
        else:
            playlist_id = await _uploads_playlist_id(
                api_key=api_key,
                channel_id=resolved_channel_id,
                client=client,
            )
            playlist_items = await _list_playlist_videos(
                api_key=api_key,
                playlist_id=playlist_id,
                client=client,
            )
            playlist_items = [
                item
                for item in playlist_items
                if _in_period(item["publishedAt"], period_start, period_end)
            ]
            video_ids = [item["videoId"] for item in playlist_items]

        if not video_ids:
            raise ConnectorError(
                "YouTube returned no videos for the reporting period — "
                "set youtubeVideoIds on integration campaignMap or widen the period"
            )

        details = await _video_details(
            api_key=api_key, video_ids=video_ids, client=client
        )
        rows = [_video_to_row(item) for item in details]
        if not rows:
            raise ConnectorError("YouTube video details returned no rows")

        return FetchResult(
            rows=rows,
            raw={
                "connector": "youtube",
                "channelId": resolved_channel_id,
                "videoIds": video_ids,
                "periodStart": period_start.isoformat(),
                "periodEnd": period_end.isoformat(),
                "note": "Watch time requires YouTube Analytics API; views from Data API v3",
            },
        )
    finally:
        if own_client:
            await client.aclose()
