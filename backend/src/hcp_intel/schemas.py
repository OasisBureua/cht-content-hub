"""Pydantic schemas for HCP Intelligence API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Tier = Literal["cold", "hot"]
FeedSource = Literal[
    "pubmed", "clinicaltrials", "youtube", "bluesky", "google_news", "openalex",
]
ResolutionStatus = Literal[
    "pending",
    "auto_resolved",
    "manually_resolved",
    "unresolved",
    "unresolvable",
    "skipped",
]
SignalType = Literal[
    "publication", "trial", "social_post", "video_upload",
    "webinar_attendance", "news_article", "email_click",
    "clip_appearance",
]
SourceField = Literal["mesh", "intervention", "title_extracted", "webinar_tag"]


class HCPBase(BaseModel):
    first_name: str
    last_name: str
    middle_name: str | None = None
    credential: str | None = None
    taxonomy: str | None = None
    taxonomy_code: str | None = None
    city: str | None = None
    state: str | None = Field(default=None, max_length=2)
    zip: str | None = None
    phone: str | None = None
    email: str | None = None
    hospital_affiliations: str | None = None
    tier: Tier = "cold"
    source: str | None = None


class HCPCreate(HCPBase):
    npi: str = Field(min_length=10, max_length=10)


class HCPUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    credential: str | None = None
    taxonomy: str | None = None
    taxonomy_code: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    phone: str | None = None
    email: str | None = None
    hospital_affiliations: str | None = None
    tier: Tier | None = None
    source: str | None = None


class HCPRead(HCPBase):
    model_config = ConfigDict(from_attributes=True)

    npi: str
    created_at: datetime
    updated_at: datetime
    # Phase 1.5 enrichment metadata
    npi_match_status: str | None = None
    npi_match_confidence: int | None = None
    npi_match_source: str | None = None
    npi_candidates: dict[str, Any] | None = None
    enrichment_data: dict[str, Any] | None = None
    commercial_targets: dict[str, Any] | None = None


class FeedSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hcp_npi: str
    source: FeedSource
    external_handle: str | None
    resolution_status: ResolutionStatus
    resolution_method: str | None
    resolution_notes: str | None
    resolved_by_user_id: str | None
    resolved_at: datetime | None
    cadence_hours: int
    last_polled_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int
    last_error: str | None
    is_active: bool
    created_at: datetime


class FeedSubscriptionCreate(BaseModel):
    source: FeedSource
    external_handle: str | None = None
    cadence_hours: int = 168


class FeedSubscriptionReview(BaseModel):
    action: Literal["confirm", "reject", "none_of_these"]
    external_handle: str | None = None
    notes: str | None = None


class SignalDrugRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    drug_normalized: str
    drug_source_term: str
    source_field: SourceField


class HCPSignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hcp_npi: str
    signal_type: SignalType
    observed_at: datetime
    source: str
    title: str | None
    url: str | None
    summary: str | None
    entities_json: dict[str, Any] | None
    drugs: list[SignalDrugRead] = []
    created_at: datetime
    # For clip_appearance: the full shoot panel (shoots.doctors), so the UI
    # can render "Podcast X — Dr. A, Dr. B" like the Content shoot dropdown.
    panel: list[str] = []


class HCPProfileRead(HCPRead):
    subscriptions: list[FeedSubscriptionRead] = []
    recent_signals: list[HCPSignalRead] = []
    # Resolved at fetch time from nci_designations against hospital_affiliations.
    # One of: elite | comprehensive | clinical | basic | community | None
    prestige_tier: str | None = None
    # KOL overlay (kol_profile) — null for non-KOL HCPs.
    is_kol: bool = False
    photo_url: str | None = None
    display_name: str | None = None


class DiscoveryQuery(BaseModel):
    drug: str | None = None
    signal_type: SignalType | None = None
    state: str | None = None
    tier: Tier | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 50


class DiscoveryHCPRow(BaseModel):
    npi: str
    first_name: str
    last_name: str
    state: str | None
    signal_count: int
    last_observed_at: datetime | None


class DiscoveryResult(BaseModel):
    total: int
    hcps: list[DiscoveryHCPRow]


# ─── Phase 1.5: webinar attendance ─────────────────────────────────────────

AttendeeStatus = Literal["needs_review", "resolved", "unresolvable"]
NPIMatchStatus = Literal["auto", "likely", "manual", "dismissed"]


class WebinarEventCreate(BaseModel):
    title: str
    topic: str | None = None
    description: str | None = None
    event_date: datetime | None = None
    indication: str | None = None


class WebinarEventRead(WebinarEventCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime


class WebinarAttendanceCreate(BaseModel):
    hcp_npi: str = Field(min_length=10, max_length=10)
    rsvped: bool = False
    attended: bool = False
    asked_question: bool = False
    watch_minutes: int | None = None
    raw_name: str | None = None
    raw_institution: str | None = None
    raw_email: str | None = None
    survey_submitted: bool = False
    notes: str | None = None


class WebinarAttendanceRead(WebinarAttendanceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    created_at: datetime


class UnmatchedAttendeeCreate(BaseModel):
    event_id: str
    raw_name: str
    raw_institution: str | None = None
    raw_email: str | None = None
    raw_phone: str | None = None
    rsvped: bool = False
    attended: bool = False
    asked_question: bool = False


class UnmatchedAttendeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    raw_name: str
    raw_institution: str | None
    raw_email: str | None
    raw_phone: str | None
    rsvped: bool
    attended: bool
    asked_question: bool
    status: AttendeeStatus
    resolved_hcp_npi: str | None
    resolved_at: datetime | None
    notes: str | None
    created_at: datetime


class UnmatchedAttendeeResolve(BaseModel):
    action: Literal["resolve", "unresolvable"]
    hcp_npi: str | None = Field(default=None, min_length=10, max_length=10)
    notes: str | None = None


# ─── Phase 1.5: webinar drug tags ──────────────────────────────────────────


class WebinarDrugRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: str
    drug_normalized: str
    drug_source_term: str
    is_primary: bool
    source: str
    created_at: datetime


class WebinarDrugsPut(BaseModel):
    """Full replacement of an event's drug tags."""
    drugs: list[str]  # free-text source terms; will be normalized server-side
    primary: str | None = None  # drug_source_term (normalized-matched) flagged as primary


# ─── Jotform form bindings ─────────────────────────────────────────────────

FormType = Literal["post_event_survey", "pre_event_poll", "follow_up"]


class WebinarFormCreate(BaseModel):
    form_id: str = Field(min_length=1, max_length=100)
    form_type: FormType = "post_event_survey"
    notes: str | None = None


class WebinarFormRead(WebinarFormCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    webinar_event_id: str
    created_at: datetime


# ─── review queue grouped ──────────────────────────────────────────────────

class ReviewQueueGroupedItem(BaseModel):
    """All unresolved subscriptions for one HCP, bundled so the UI can
    render a single card per HCP instead of duplicating the identity card
    for each source."""
    model_config = ConfigDict(from_attributes=True)
    hcp: "HCPRead"  # forward ref — already defined above
    subscriptions: list["FeedSubscriptionRead"]


class ReviewQueueGroupedResponse(BaseModel):
    total_hcps: int
    total_subs: int
    items: list[ReviewQueueGroupedItem]


# ─── Rx volumes ────────────────────────────────────────────────────────────


class RxVolumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    drug_normalized: str
    brand_name: str | None
    generic_name: str | None
    rxcui: str | None
    year: int
    quarter: int | None
    total_claims: int | None
    total_beneficiaries: int | None
    total_drug_cost: float | None
    source: str


class RxVolumesByDrug(BaseModel):
    """Per-drug Rx history rolled up across years."""
    drug_normalized: str
    brand_name: str | None
    drug_class: str | None
    total_claims_all_years: int
    total_drug_cost_all_years: float | None
    years: list[RxVolumeRead]
