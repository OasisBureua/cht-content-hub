"""Swappable platform export clients.

Mappers/upserts only see ``PlatformExportPacket``. HTTP path differences
(``input-packet`` vs CPR-12 ``/api/export/v1/*``) stay inside the client.
"""

from __future__ import annotations

from typing import Protocol

from schemas.platform_export import PlatformExportPacket


class ExportClientError(RuntimeError):
    """Raised when the export API or fixture source cannot be read."""


class ExportClient(Protocol):
    """Fetches (or assembles) a campaign-scoped export packet."""

    async def fetch_campaign_packet(self, campaign_id: int) -> PlatformExportPacket:
        """Return the canonical ingest packet for a Hub campaign id."""
        ...
