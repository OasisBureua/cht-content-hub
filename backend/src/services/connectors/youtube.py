"""YouTube Data API v3 connector (API key).

CPR-15: the daily sync lists every upload on the CHM channels and reads each
video's lifetime views, likes and comments. The Data API only returns
lifetime totals, so history comes from storing one snapshot per day. Watch
time and retention need the YouTube Analytics API with channel-owner OAuth
(not used here).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from services.connectors.common import (
    ConnectorError,
    request_failed,
    response_json,
)

log = logging.getLogger(__name__)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
_ISO_DURATION = re.compile(
    r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
    re.IGNORECASE,
)
_PAGE = 50


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    channel_id: str
    channel_title: str
    title: str
    description: str
    published_at: datetime | None
    thumbnail_url: str | None
    duration_seconds: int | None
    live_broadcast: str
    views: int
    likes: int
    comments: int

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def duration_seconds(duration: str) -> int | None:
    """ISO 8601 duration (``PT1H2M3S``) in seconds; None when unparseable."""
    match = _ISO_DURATION.fullmatch((duration or "").strip())
    if not duration or not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def uploads_playlist_id(channel_id: str) -> str:
    """Every channel's uploads playlist is its ID with ``UC`` swapped for ``UU``."""
    if not channel_id.startswith("UC"):
        raise ConnectorError(f"Not a YouTube channel ID: {channel_id}")
    return "UU" + channel_id[2:]


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _video(item: dict[str, Any]) -> YouTubeVideo:
    snippet = item.get("snippet") or {}
    statistics = item.get("statistics") or {}
    thumbnails = snippet.get("thumbnails") or {}
    thumb = next(
        (thumbnails[size]["url"] for size in ("high", "medium", "default") if size in thumbnails),
        None,
    )
    return YouTubeVideo(
        video_id=item.get("id") or "",
        channel_id=snippet.get("channelId") or "",
        channel_title=snippet.get("channelTitle") or "",
        title=snippet.get("title") or "",
        description=snippet.get("description") or "",
        published_at=_published(snippet.get("publishedAt")),
        thumbnail_url=thumb,
        duration_seconds=duration_seconds((item.get("contentDetails") or {}).get("duration") or ""),
        live_broadcast=snippet.get("liveBroadcastContent") or "none",
        views=int(statistics.get("viewCount") or 0),
        likes=int(statistics.get("likeCount") or 0),
        comments=int(statistics.get("commentCount") or 0),
    )


async def _get(
    client: httpx.AsyncClient, path: str, params: dict[str, Any], what: str, *, api_key: str
) -> Any:
    # The key goes in a header: request URLs are logged (httpx INFO).
    try:
        response = await client.get(
            f"{YOUTUBE_API}/{path}", params=params, headers={"X-Goog-Api-Key": api_key}
        )
    except httpx.HTTPError as exc:
        raise request_failed(what, exc) from exc
    if response.status_code >= 400:
        raise ConnectorError(f"{what} failed {response.status_code}: {response.text[:300]}")
    return response_json(response, what)


async def list_playlist_video_ids(
    *, api_key: str, playlist_id: str, client: httpx.AsyncClient
) -> list[str]:
    """Video IDs in a playlist, in playlist order (1 quota unit per 50)."""
    ids: list[str] = []
    page_token = ""
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": _PAGE}
        if page_token:
            params["pageToken"] = page_token
        payload = await _get(
            client, "playlistItems", params, "YouTube playlistItems.list", api_key=api_key
        )
        for entry in payload.get("items") or []:
            video_id = (entry.get("contentDetails") or {}).get("videoId")
            if video_id:
                ids.append(video_id)
        page_token = payload.get("nextPageToken") or ""
        if not page_token:
            return ids


async def fetch_videos(
    *, api_key: str, video_ids: list[str], client: httpx.AsyncClient
) -> list[YouTubeVideo]:
    """Details and lifetime counts; private or deleted videos are left out."""
    videos: list[YouTubeVideo] = []
    unique = list(dict.fromkeys(video_ids))
    for offset in range(0, len(unique), _PAGE):
        payload = await _get(
            client,
            "videos",
            {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(unique[offset : offset + _PAGE]),
            },
            "YouTube videos.list",
            api_key=api_key,
        )
        videos.extend(_video(item) for item in payload.get("items") or [])
    return videos
