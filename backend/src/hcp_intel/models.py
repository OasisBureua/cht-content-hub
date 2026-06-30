"""HCP Intelligence models.

Six tables:
- feed_sources: registry of supported sources (pubmed, clinicaltrials, ...)
- hcps: identity record (NPI natural key)
- feed_subscriptions: one per (HCP, source), carries polling state
- feed_items: raw items from source APIs (idempotent on external_id)
- hcp_signals: derived facts — the product
- signal_drugs: join table with hcp_npi/observed_at denormalized for fast discovery
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class FeedSource(Base):
    """Registry of data sources. Seeded in migration."""

    __tablename__ = "feed_sources"

    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    default_cadence_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_limit_per_second: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )


class HCP(Base):
    """Healthcare provider identity record."""

    __tablename__ = "hcps"

    npi: Mapped[str] = mapped_column(String(10), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credential: Mapped[str | None] = mapped_column(String(50), nullable=True)
    taxonomy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    taxonomy_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip: Mapped[str | None] = mapped_column(String(10), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hospital_affiliations: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[str] = mapped_column(
        String(10), nullable=False, default="cold", server_default="cold"
    )
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # NPI enrichment metadata — why was this NPI chosen?
    npi_match_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="auto", server_default="auto"
    )  # 'auto' | 'likely' | 'manual' | 'dismissed'
    npi_match_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    npi_match_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    npi_candidates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    npi_resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enrichment_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    commercial_targets: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # True for the CHM KOLs — HCPs we actively produce content with. The
    # CHM-curated overlay (bio, photo, region, slug) lives in kol_profile,
    # keyed by this NPI. See migration d8e9f0a1b2c3.
    is_kol: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # OpenAlex author-ID resolution (research-activity disambiguation).
    openalex_author_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    openalex_resolution_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unresolved", server_default="unresolved"
    )  # 'unresolved' | 'auto_locked' | 'needs_review' | 'manually_locked' | 'no_match'
    openalex_resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    openalex_candidates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    subscriptions: Mapped[list["FeedSubscription"]] = relationship(
        back_populates="hcp", cascade="all, delete-orphan"
    )
    signals: Mapped[list["HCPSignal"]] = relationship(
        back_populates="hcp", cascade="all, delete-orphan"
    )
    attendance: Mapped[list["WebinarAttendance"]] = relationship(
        back_populates="hcp", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_hcps_tier", "tier"),
        Index("ix_hcps_state", "state"),
        Index("ix_hcps_email_lower", func.lower(email)),
        Index("ix_hcps_lastname_lower", func.lower(last_name)),
    )

    def __repr__(self) -> str:
        return f"<HCP {self.npi} {self.last_name}, {self.first_name} ({self.tier})>"


class FeedSubscription(Base):
    """One row per (HCP, source). Carries polling state."""

    __tablename__ = "feed_subscriptions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    hcp_npi: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("hcps.npi", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(30),
        ForeignKey("feed_sources.name"),
        nullable=False,
    )
    external_handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolution_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    resolution_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cadence_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=168, server_default="168"
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    hcp: Mapped[HCP] = relationship(back_populates="subscriptions")
    items: Mapped[list["FeedItem"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("hcp_npi", "source", name="uq_subs_hcp_source"),
        Index("ix_subs_due", "is_active", "resolution_status", "last_polled_at"),
        Index(
            "ix_subs_review",
            "resolution_status",
            postgresql_where="resolution_status IN ('pending', 'unresolved')",
        ),
    )


class FeedItem(Base):
    """Raw items as they come back from APIs."""

    __tablename__ = "feed_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    subscription_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feed_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    subscription: Mapped[FeedSubscription] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "external_id", name="uq_items_subscription_external"
        ),
        Index(
            "ix_items_subscription_published",
            "subscription_id",
            "published_at",
        ),
    )


class HCPSignal(Base):
    """Derived fact about an HCP — the product."""

    __tablename__ = "hcp_signals"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    hcp_npi: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("hcps.npi", ondelete="CASCADE"),
        nullable=False,
    )
    signal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    derived_from_item_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("feed_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    hcp: Mapped[HCP] = relationship(back_populates="signals")
    drugs: Mapped[list["SignalDrug"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_signals_hcp_observed", "hcp_npi", "observed_at"),
        Index("ix_signals_type_observed", "signal_type", "observed_at"),
        Index("ix_signals_source", "source"),
    )


class SignalDrug(Base):
    """Join table: one row per drug per signal. Anchors cross-HCP discovery.

    `hcp_npi` and `observed_at` are denormalized from `hcp_signals` so the
    `(drug_normalized, observed_at)` index covers the discovery query with no
    join back. Publications/trials never update, so denorm stays consistent.
    """

    __tablename__ = "signal_drugs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    signal_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("hcp_signals.id", ondelete="CASCADE"),
        nullable=False,
    )
    hcp_npi: Mapped[str] = mapped_column(String(10), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    drug_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    drug_source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    source_field: Mapped[str] = mapped_column(String(30), nullable=False)

    signal: Mapped[HCPSignal] = relationship(back_populates="drugs")

    __table_args__ = (
        UniqueConstraint(
            "signal_id", "drug_normalized", name="uq_signal_drugs_signal_drug"
        ),
        Index("ix_signal_drugs_discovery", "drug_normalized", "observed_at"),
        Index(
            "ix_signal_drugs_hcp_timeline",
            "hcp_npi",
            "drug_normalized",
            "observed_at",
        ),
    )


class WebinarEvent(Base):
    """A CHM webinar. One row per event."""

    __tablename__ = "webinar_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    indication: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    attendance: Mapped[list["WebinarAttendance"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    unmatched: Mapped[list["UnmatchedAttendee"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_webinar_events_date", "event_date"),)


class WebinarAttendance(Base):
    """One row per (HCP, webinar). Per-session engagement flags."""

    __tablename__ = "webinar_attendance"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("webinar_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    hcp_npi: Mapped[str] = mapped_column(
        String(10), ForeignKey("hcps.npi", ondelete="CASCADE"), nullable=False
    )
    rsvped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    attended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    asked_question: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    watch_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    survey_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    event: Mapped[WebinarEvent] = relationship(back_populates="attendance")
    hcp: Mapped[HCP] = relationship(back_populates="attendance")

    __table_args__ = (
        UniqueConstraint("event_id", "hcp_npi", name="uq_attendance_event_hcp"),
        Index("ix_attendance_hcp", "hcp_npi"),
        Index("ix_attendance_event", "event_id"),
    )


class UnmatchedAttendee(Base):
    """Survey row whose raw_name couldn't be auto-linked to an HCP."""

    __tablename__ = "unmatched_attendees"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("webinar_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rsvped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    attended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    asked_question: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="needs_review", server_default="needs_review"
    )
    resolved_hcp_npi: Mapped[str | None] = mapped_column(
        String(10), ForeignKey("hcps.npi", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    event: Mapped[WebinarEvent] = relationship(back_populates="unmatched")

    __table_args__ = (
        Index("ix_unmatched_status", "status"),
        Index("ix_unmatched_event", "event_id"),
    )


class WebinarDrug(Base):
    """Drug tagged on a webinar event. Many-to-many via composite PK."""

    __tablename__ = "webinar_drugs"

    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("webinar_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    drug_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    drug_source_term: Mapped[str] = mapped_column(String(255), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="extracted", server_default="extracted"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("event_id", "drug_normalized", name="pk_webinar_drugs"),
        Index("ix_webinar_drugs_drug", "drug_normalized"),
    )


class WebinarForm(Base):
    """Jotform form ↔ webinar event binding. Many-to-many."""

    __tablename__ = "webinar_forms"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    webinar_event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("webinar_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    form_id: Mapped[str] = mapped_column(String(100), nullable=False)
    form_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="post_event_survey",
        server_default="post_event_survey",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "webinar_event_id", "form_id", "form_type", name="uq_webinar_form_triple"
        ),
        Index("ix_webinar_forms_form_id", "form_id"),
    )


class RxVolume(Base):
    """Per-HCP per-drug per-year prescription volumes."""

    __tablename__ = "rx_volumes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    hcp_npi: Mapped[str] = mapped_column(
        String(10), ForeignKey("hcps.npi", ondelete="CASCADE"), nullable=False
    )
    drug_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generic_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rxcui: Mapped[str | None] = mapped_column(String(20), nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_claims: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_beneficiaries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_30day_fills: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    total_day_supply: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_drug_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    ge65_total_claims: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ge65_total_drug_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="cms_part_d", server_default="cms_part_d"
    )
    year_released: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "hcp_npi", "drug_normalized", "year", "source",
            name="uq_rx_volumes_hcp_drug_year_source",
        ),
        Index("ix_rx_volumes_hcp_year", "hcp_npi", "year"),
        Index("ix_rx_volumes_drug_year", "drug_normalized", "year"),
        Index("ix_rx_volumes_rxcui", "rxcui"),
    )


class RxDrugAlias(Base):
    """RxNorm-resolved canonical names keyed on source term (brand or generic)."""

    __tablename__ = "rx_drug_aliases"

    source_term: Mapped[str] = mapped_column(String(255), primary_key=True)
    rxcui: Mapped[str | None] = mapped_column(String(20), nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_normalized: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tty: Mapped[str | None] = mapped_column(String(10), nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_rx_drug_aliases_normalized", "canonical_normalized"),
    )


class DrugClass(Base):
    """Oncology drug class taxonomy. Seeded in migration."""

    __tablename__ = "drug_classes"

    class_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mechanism: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )


class DrugToClass(Base):
    """Mapping of normalized drug names → class."""

    __tablename__ = "drug_to_class"

    drug_normalized: Mapped[str] = mapped_column(String(100), primary_key=True)
    class_name: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("drug_classes.class_name", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (Index("ix_drug_to_class_class", "class_name"),)


class HCPAIBrief(Base):
    """Cached Claude-generated briefing for an HCP. One row per NPI.

    Regenerated on demand via POST; GET returns the cached row. TTL is
    enforced at the application layer (7d) — a stale row still returns 200
    but callers can inspect `generated_at` to decide whether to refresh.
    """

    __tablename__ = "hcp_ai_briefs"

    hcp_npi: Mapped[str] = mapped_column(
        String(10), ForeignKey("hcps.npi", ondelete="CASCADE"), primary_key=True,
    )
    brief_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(String(60), nullable=False)
    input_signal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_rx_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )
    generated_by_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )


class NCIDesignation(Base):
    """NCI-designated cancer centers. Used for hospital prestige tier in
    KOL scoring. Seeded from the public NCI list; admin can override.
    """

    __tablename__ = "nci_designations"

    institution_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'elite' | 'comprehensive' | 'clinical' | 'basic' | 'community'
    designation_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )


class Manufacturer(Base):
    """Pharma company brand color lookup. Used for medication chips."""

    __tablename__ = "manufacturers"

    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    brand_color: Mapped[str | None] = mapped_column(String(12), nullable=True)
    secondary_color: Mapped[str | None] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )


class Medication(Base):
    """Oncology medication catalog. Powers the Medications landscape page.

    Keyed on drug_normalized (same key used everywhere else in hcp_intel)
    so joins with rx_volumes and signal_drugs are trivial.
    """

    __tablename__ = "medications"

    drug_normalized: Mapped[str] = mapped_column(String(100), primary_key=True)
    brand_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    generic_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    drug_class: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("drug_classes.class_name", ondelete="SET NULL"),
        nullable=True,
    )
    manufacturer: Mapped[str | None] = mapped_column(
        String(120),
        ForeignKey("manufacturers.name", ondelete="SET NULL"),
        nullable=True,
    )
    fda_approval_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indication: Mapped[str | None] = mapped_column(Text, nullable=True)
    indication_short: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rxcui: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_medications_class", "drug_class"),
        Index("ix_medications_manufacturer", "manufacturer"),
    )


class OpenPaymentsRecord(Base):
    """One row per disclosed pharma→physician payment from CMS Open Payments
    (Sunshine Act). Sourced by NPI via data.cms.gov datastore API.

    Payment_type is one of:
      'general'   — meals, travel, speaker/consulting fees, gifts, honoraria
      'research' — research grants (PI-level)
      'ownership' — ownership/investment interests
    """

    __tablename__ = "open_payments_records"

    record_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    hcp_npi: Mapped[str] = mapped_column(
        String(10), ForeignKey("hcps.npi", ondelete="CASCADE"), nullable=False
    )
    program_year: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_type: Mapped[str] = mapped_column(String(12), nullable=False)
    payment_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    amount_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    nature_of_payment: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    drug_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    drug_normalized: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_open_payments_hcp_year", "hcp_npi", "program_year"),
        Index("ix_open_payments_drug", "drug_normalized"),
        Index("ix_open_payments_company", "company_name"),
    )


class NIHGrant(Base):
    """NIH RePORTER grant records matched to an HCP by PI name.

    NIH doesn't expose NPIs on grant records, so the match is name-only
    (first + last). False-positive risk is low for unique-named researchers
    but real for common names — we keep the org name in `organization`
    so a reviewer can confirm "this Tolaney is the Dana-Farber one."

    Keyed on appl_id (NIH's unique application ID).
    """

    __tablename__ = "hcp_nih_grants"

    appl_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    hcp_npi: Mapped[str] = mapped_column(
        String(10), ForeignKey("hcps.npi", ondelete="CASCADE"), nullable=False
    )
    project_num: Mapped[str | None] = mapped_column(String(60), nullable=True)
    project_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    award_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    activity_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    agency_ic: Mapped[str | None] = mapped_column(String(50), nullable=True)
    agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_start_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    project_end_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    pi_first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pi_last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_nih_grants_hcp_fy", "hcp_npi", "fiscal_year"),
        Index("ix_nih_grants_active", "is_active"),
    )


class DataSyncState(Base):
    """Tracks last successful run of long-running external-data sync jobs.

    One row per named sync (e.g. `supabase_contacts`). Idempotent upsert
    keyed on sync_name. Lets the nightly diff job know where to resume.
    """

    __tablename__ = "data_sync_state"

    sync_name: Mapped[str] = mapped_column(String(60), primary_key=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rows_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )
