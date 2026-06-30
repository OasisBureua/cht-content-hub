"""YouTube channel feed fetcher.

Uses the public Atom feed: `https://www.youtube.com/feeds/videos.xml?channel_id=...`.
Channel IDs are bound manually via admin UI — no auto-discovery in v1.

Drug extraction from video titles is NOT done in v1 (would need NLP); signals
land as `video_upload` with empty drugs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from lxml import etree

from .common import FeedItemPayload, SignalPayload

log = logging.getLogger(__name__)

FEED = "https://www.youtube.com/feeds/videos.xml"
UA = "CHM-MediaHub-FeedFetcher/0.1 (sebastien@communityhealth.media)"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def _text(el: etree._Element | None, xpath: str, ns: dict[str, str] = _NS) -> str:
    if el is None:
        return ""
    found = el.find(xpath, ns)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_feed(xml_bytes: bytes) -> list[FeedItemPayload]:
    if not xml_bytes:
        return []
    root = etree.fromstring(xml_bytes)
    items: list[FeedItemPayload] = []
    for entry in root.findall("atom:entry", _NS):
        video_id = _text(entry, "yt:videoId")
        title = _text(entry, "atom:title")
        published = _text(entry, "atom:published")
        link_el = entry.find("atom:link", _NS)
        url = link_el.get("href") if link_el is not None else None
        pub_at: datetime | None
        try:
            pub_at = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
        except ValueError:
            pub_at = None
        channel_id_el = root.find("yt:channelId", _NS)
        channel_id = channel_id_el.text if channel_id_el is not None else ""
        items.append(
            FeedItemPayload(
                external_id=video_id,
                title=title,
                url=url,
                published_at=pub_at.replace(tzinfo=None) if pub_at else None,
                raw={
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "published_raw": published,
                },
            )
        )
    return items


async def fetch_for_channel(
    channel_id: str, *, client: httpx.AsyncClient | None = None
) -> list[FeedItemPayload]:
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        r = await client.get(
            FEED, params={"channel_id": channel_id}, headers={"User-Agent": UA}
        )
        r.raise_for_status()
        return parse_feed(r.content)
    finally:
        if own:
            await client.aclose()


def extract_signals(item: FeedItemPayload) -> list[SignalPayload]:
    if item.published_at is None:
        return []
    return [
        SignalPayload(
            signal_type="video_upload",
            observed_at=item.published_at,
            title=item.title,
            url=item.url,
            summary=None,
            entities={
                "video_id": (item.raw or {}).get("video_id") or item.external_id,
                "channel_id": (item.raw or {}).get("channel_id"),
            },
            drugs=[],
        )
    ]
