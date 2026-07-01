"""Bluesky profile RSS fetcher.

Uses `https://bsky.app/profile/{handle}/rss`. Handles are bound manually.

Drug extraction from post text is NOT done in v1.
"""

from __future__ import annotations

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
from lxml import etree

from .common import FeedItemPayload, SignalPayload

log = logging.getLogger(__name__)

BASE = "https://bsky.app/profile/{handle}/rss"
UA = "CHM-MediaHub-FeedFetcher/0.1 (sebastien@communityhealth.media)"


def _text(el: etree._Element | None, tag: str) -> str:
    if el is None:
        return ""
    child = el.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def parse_feed(xml_bytes: bytes) -> list[FeedItemPayload]:
    if not xml_bytes:
        return []
    root = etree.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return []
    out: list[FeedItemPayload] = []
    for item in channel.findall("item"):
        guid = _text(item, "guid") or _text(item, "link")
        title = _text(item, "title")
        link = _text(item, "link")
        pub_date_raw = _text(item, "pubDate")
        pub_at: datetime | None = None
        if pub_date_raw:
            try:
                pub_at = parsedate_to_datetime(pub_date_raw).replace(tzinfo=None)
            except (TypeError, ValueError):
                pub_at = None
        out.append(
            FeedItemPayload(
                external_id=guid,
                title=title,
                url=link,
                published_at=pub_at,
                raw={
                    "guid": guid,
                    "description": _text(item, "description"),
                },
            )
        )
    return out


async def fetch_for_handle(
    handle: str, *, client: httpx.AsyncClient | None = None
) -> list[FeedItemPayload]:
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        r = await client.get(BASE.format(handle=handle), headers={"User-Agent": UA})
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
            signal_type="social_post",
            observed_at=item.published_at,
            title=item.title,
            url=item.url,
            summary=(item.raw or {}).get("description"),
            entities={
                "post_uri": item.external_id,
            },
            drugs=[],
        )
    ]
