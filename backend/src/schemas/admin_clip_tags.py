"""Admin clip-tag API schemas (SCRUM-75)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClipTagsOut(BaseModel):
    """Admin-facing clip tag view."""

    id: str
    tags: list[str] = Field(default_factory=list)
    tags_curator_override: bool = False


class ClipTagsUpdate(BaseModel):
    """PATCH body — every field optional; omitted fields are untouched.

    tags is fully replaced (not merged). tags_curator_override defaults
    True on any tag write so a curator edit auto-locks against the tagger's
    daily overwrite. Setting it explicitly False re-opens the row to the
    tagger (rare — typically a rollback).
    """

    tags: list[str] | None = None
    tags_curator_override: bool | None = None
