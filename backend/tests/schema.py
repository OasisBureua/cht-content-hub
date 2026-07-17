"""Create a minimal schema for integration tests (no Docker / Postgres required)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from database import Base
from hcp_intel.models import HCP
from models.campaign import (
    Campaign,
    CampaignPlatformData,
    IntegrationSetting,
    PlatformSyncRun,
    ReportTemplate,
)
from models.client import Client
from models.clip import Clip
from models.kol import KOL, KOLGroup, KOLGroupMember
from models.playlist_tag import PlaylistTag
from models.post import Post
from models.project import Project
from models.shoot import Shoot

ORM_TABLES = [
    ReportTemplate.__table__,
    Campaign.__table__,
    CampaignPlatformData.__table__,
    PlatformSyncRun.__table__,
    IntegrationSetting.__table__,
    Client.__table__,
    Project.__table__,
    HCP.__table__,
    KOL.__table__,
    KOLGroup.__table__,
    KOLGroupMember.__table__,
    PlaylistTag.__table__,
    Shoot.__table__,
    Clip.__table__,
    Post.__table__,
]

_HCP_SIGNALS_DDL = """
CREATE TABLE IF NOT EXISTS hcp_signals (
    id VARCHAR(36) PRIMARY KEY,
    hcp_npi VARCHAR(10) NOT NULL REFERENCES hcps(npi),
    signal_type VARCHAR(30) NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    source VARCHAR(30) NOT NULL,
    derived_from_item_id VARCHAR(36),
    title TEXT,
    url TEXT,
    summary TEXT,
    entities_json JSON,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# `wordpress_events` uses postgres JSONB in the ORM model, which SQLite can't
# create via Base.metadata.create_all. Mirror it as a raw DDL with JSON columns —
# tests only need list-shaped read/write, not Postgres-specific operators.
# WebinarEvent + WebinarAttendance + OpenPaymentsRecord mirror the ORM models
# with SQLite-compatible types (Postgres UUID / JSONB / Numeric become VARCHAR /
# JSON / REAL). Tests only exercise basic read/write, not Postgres-specific
# operators.
_WEBINAR_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS webinar_events (
    id VARCHAR(36) PRIMARY KEY,
    zoom_webinar_id VARCHAR(50),
    title VARCHAR(500),
    scheduled_start TIMESTAMP,
    duration_minutes INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_WEBINAR_ATTENDANCE_DDL = """
CREATE TABLE IF NOT EXISTS webinar_attendance (
    id VARCHAR(36) PRIMARY KEY,
    event_id VARCHAR(36) NOT NULL REFERENCES webinar_events(id),
    hcp_npi VARCHAR(10) NOT NULL REFERENCES hcps(npi),
    rsvped BOOLEAN NOT NULL DEFAULT 0,
    attended BOOLEAN NOT NULL DEFAULT 0,
    asked_question BOOLEAN NOT NULL DEFAULT 0,
    watch_minutes INTEGER,
    raw_name VARCHAR(255),
    raw_institution VARCHAR(255),
    raw_email VARCHAR(255),
    survey_submitted BOOLEAN NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_OPEN_PAYMENTS_DDL = """
CREATE TABLE IF NOT EXISTS open_payments_records (
    record_id VARCHAR(60) PRIMARY KEY,
    hcp_npi VARCHAR(10) NOT NULL REFERENCES hcps(npi),
    program_year INTEGER NOT NULL,
    payment_type VARCHAR(12) NOT NULL,
    payment_date TIMESTAMP,
    amount_usd REAL,
    nature_of_payment TEXT,
    company_name TEXT,
    drug_name TEXT,
    drug_normalized VARCHAR(100),
    raw_json JSON,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_WORDPRESS_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS wordpress_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    modified_gmt TIMESTAMP NOT NULL,
    event VARCHAR(16) NOT NULL,
    post_type VARCHAR(64) NOT NULL,
    slug VARCHAR(500) NOT NULL,
    title TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    permalink VARCHAR(1000) NOT NULL,
    categories JSON NOT NULL DEFAULT '[]',
    tags JSON NOT NULL DEFAULT '[]',
    site_url VARCHAR(500) NOT NULL,
    acf JSON,
    raw_payload JSON NOT NULL,
    signature_verified BOOLEAN NOT NULL DEFAULT 1,
    received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    youtube_video_id VARCHAR(20),
    featured_media_url TEXT,
    UNIQUE (post_id, modified_gmt)
)
"""


async def create_test_schema(conn: AsyncConnection) -> None:
    await conn.run_sync(
        lambda sync_conn: Base.metadata.create_all(
            sync_conn, tables=ORM_TABLES, checkfirst=True
        )
    )
    await conn.execute(text(_HCP_SIGNALS_DDL))
    await conn.execute(text(_WEBINAR_EVENTS_DDL))
    await conn.execute(text(_WEBINAR_ATTENDANCE_DDL))
    await conn.execute(text(_OPEN_PAYMENTS_DDL))
    await conn.execute(text(_WORDPRESS_EVENTS_DDL))
