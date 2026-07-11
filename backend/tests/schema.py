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
    await conn.execute(text(_WORDPRESS_EVENTS_DDL))
