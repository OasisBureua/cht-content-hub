"""Public API schemas — KOL network (Step 3)."""

from datetime import datetime

from pydantic import BaseModel


class PublicKOLIntel(BaseModel):
    """Optional HCP Intel overlay — mirrors CHT KolIntel subset for /kol-network."""

    npi: str | None = None
    specialty: str | None = None
    location: str | None = None
    email: str | None = None
    affiliation: str | None = None
    publications_approx: int | None = None
    open_payments: dict | None = None
    ai_brief: dict | None = None


class PublicKOL(BaseModel):
    id: str
    slug: str
    name: str
    title: str | None
    specialty: str | None
    institution: str | None
    bio: str | None
    photo_url: str | None
    region: str | None
    region_label: str | None
    shoot_count: int
    first_appeared_at: datetime | None
    is_new: bool
    intel: PublicKOLIntel | None = None


class PublicKOLRegion(BaseModel):
    slug: str
    label: str
    kol_count: int


class PublicKOLList(BaseModel):
    items: list[PublicKOL]
    total: int
    regions: list[PublicKOLRegion]
    institutions: list[str]


class PublicKOLPublication(BaseModel):
    title: str
    url: str | None
    journal: str | None
    published_at: datetime
    is_first_author: bool = False
    is_last_author: bool = False


class PublicKOLPublicationList(BaseModel):
    items: list[PublicKOLPublication]
    total: int


class HCPUpsertRequest(BaseModel):
    """CHT registration sync — snake_case body matches mediahub-sync.service.ts."""

    npi: str
    first_name: str
    last_name: str
    email: str | None = None
    specialty: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    institution: str | None = None
    source: str = "cht"


class HCPUpsertResponse(BaseModel):
    created: bool
    npi: str
