"""Admin KOL API schemas (SCRUM-58)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KOLAdminOut(BaseModel):
    """Admin-facing KOL row.

    Superset of PublicKOL. Adds the admin-editable fields (display_order,
    featured), the curated-fields lock list, and the raw hcp_match_status
    so the admin UI can distinguish auto vs manually-locked KOLs.
    """

    id: str
    slug: str
    name: str
    title: str | None = None
    specialty: str | None = None
    institution: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    region: str | None = None
    region_label: str | None = None
    display_order: int | None = None
    featured: bool = False
    curated_fields: list[str] = Field(default_factory=list)
    hcp_npi: str | None = None
    hcp_match_status: str = "unresolved"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KOLAdminListOut(BaseModel):
    items: list[KOLAdminOut]
    total: int


class KOLAdminUpdate(BaseModel):
    """PATCH payload. Every field optional — omitted fields are untouched.

    Fields listed here map 1:1 to `services.kol_write.EDITABLE_FIELDS`; the
    write helper enforces the allowlist and marks each supplied field as
    curated so sync jobs do not overwrite admin edits.
    """

    title: str | None = None
    specialty: str | None = None
    institution: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    region: str | None = None
    display_order: int | None = None
    featured: bool | None = None


class KOLRefreshOut(BaseModel):
    """Response for POST /api/admin/kols/{slug}/refresh."""

    status: str  # "enqueued" | "no_op" | "cooldown"
    reason: str | None = None
    slug: str
    hcp_npi: str | None = None
    cooldown_remaining_seconds: int | None = None


class KOLHeadshotPresignRequest(BaseModel):
    """POST body for /api/admin/kols/{slug}/headshot/presign."""

    content_type: str = Field(pattern=r"^image/(jpeg|jpg|png|webp)$")


class KOLHeadshotPresignOut(BaseModel):
    """Presigned S3 PUT URL for direct browser upload."""

    upload_url: str
    upload_method: str = "PUT"
    upload_headers: dict[str, str]
    key: str
    photo_url: str
    expires_in_seconds: int
