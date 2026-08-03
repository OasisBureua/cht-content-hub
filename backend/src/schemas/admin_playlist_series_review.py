"""Schemas for the playlist-series review admin API (WPR-6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PlaylistSeriesReviewOut(BaseModel):
    id: int
    youtube_playlist_id: str
    wp_series_slug: str
    match_score: float
    signals: dict[str, Any]
    status: str
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None


class PlaylistSeriesReviewList(BaseModel):
    items: list[PlaylistSeriesReviewOut]
    total: int


class PlaylistSeriesReviewCreate(BaseModel):
    """Body for POST /playlist-series-review — insert a new candidate."""

    youtube_playlist_id: str = Field(min_length=1, max_length=64)
    wp_series_slug: str = Field(min_length=1, max_length=200)
    match_score: float = Field(ge=0.0, le=1.0)
    signals: dict[str, Any] = Field(default_factory=dict)


class PlaylistSeriesReviewDecision(BaseModel):
    """Body for approve / reject endpoints."""

    reviewed_by: str = Field(
        min_length=1,
        max_length=200,
        description="Curator identity — free-text until CHT auth wires in",
    )
