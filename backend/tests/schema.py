"""Create a minimal schema for integration tests (no Docker / Postgres required)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from database import Base
from hcp_intel.models import HCP
from models.client import Client
from models.kol import KOL, KOLGroup, KOLGroupMember
from models.playlist_tag import PlaylistTag
from models.project import Project
from models.shoot import Shoot

ORM_TABLES = [
    Client.__table__,
    Project.__table__,
    HCP.__table__,
    KOL.__table__,
    KOLGroup.__table__,
    KOLGroupMember.__table__,
    PlaylistTag.__table__,
    Shoot.__table__,
]

# Avoid feed_items FK chain from the full hcp_intel model graph.
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


async def create_test_schema(conn: AsyncConnection) -> None:
    await conn.run_sync(
        lambda sync_conn: Base.metadata.create_all(
            sync_conn, tables=ORM_TABLES, checkfirst=True
        )
    )
    await conn.execute(text(_HCP_SIGNALS_DDL))
