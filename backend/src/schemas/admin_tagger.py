"""Admin tagger observability schemas (SCRUM-78)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TaggerRunOut(BaseModel):
    id: str
    started_at: datetime
    finished_at: datetime
    mode: str
    dry_run: bool
    shoots_processed: int
    shoots_doctors_corrected: int
    clips_changed: int
    posts_changed: int
    clips_curator_locked_skipped: int
    posts_curator_locked_skipped: int
    orphaned_404_count: int
    api_error_count: int
    clip_post_skipped_models_missing: bool


class TaggerRunList(BaseModel):
    items: list[TaggerRunOut] = Field(default_factory=list)
    total: int


class TagDiffOut(BaseModel):
    id: str
    run_id: str
    entity_type: str
    entity_id: str
    shoot_id: str
    shoot_name: str
    provider_post_id: str | None = None
    title: str | None = None
    before_tags: list[str] = Field(default_factory=list)
    after_tags: list[str] = Field(default_factory=list)
    created_at: datetime


class TagDiffList(BaseModel):
    items: list[TagDiffOut] = Field(default_factory=list)
    total: int
