"""Admin playlist-tag API schemas (SCRUM-74)."""

from __future__ import annotations

from pydantic import BaseModel, Field


ALLOWED_LANES = {"biomarker", "drug", "trial", "doctor_pair", "mixed", "archive"}


class PlaylistTagOut(BaseModel):
    """Admin-facing playlist tag row."""

    youtube_playlist_id: str
    tags: list[str] = Field(default_factory=list)
    lane: str | None = None


class PlaylistTagUpdate(BaseModel):
    """PATCH body — every field optional; omitted fields are untouched.

    tags is fully replaced (not merged). Curator sees the current tag list
    in the UI and edits from there; no need to expose incremental add/remove.
    lane accepts one of ALLOWED_LANES or null to clear.
    """

    tags: list[str] | None = None
    lane: str | None = None


class PlaylistTagRejection(BaseModel):
    tag: str
    reason: str


class PlaylistTagValidationError(BaseModel):
    """422 body when one or more tags fail taxonomy validation."""

    detail: str
    rejected: list[PlaylistTagRejection]
