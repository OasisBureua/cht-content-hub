"""Shared typed payloads used by all feed sources."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FeedItemPayload:
    """What a fetcher returns for one item. Persisted 1:1 to feed_items."""

    external_id: str
    title: str
    url: str | None
    published_at: datetime | None
    raw: dict[str, Any]


@dataclass
class DrugPayload:
    """One drug reference on a signal."""

    drug_source_term: str
    drug_normalized: str
    source_field: str  # 'mesh' | 'intervention' | 'title_extracted'


@dataclass
class SignalPayload:
    """What extract_signals() returns. Persisted to hcp_signals + signal_drugs."""

    signal_type: str
    observed_at: datetime
    title: str | None = None
    url: str | None = None
    summary: str | None = None
    entities: dict[str, Any] | None = None
    drugs: list[DrugPayload] = field(default_factory=list)
