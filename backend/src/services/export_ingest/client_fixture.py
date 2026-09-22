"""Fixture / in-memory export client for offline CPR-13 development."""

from __future__ import annotations

import json
from pathlib import Path

from schemas.platform_export import PlatformExportPacket
from services.export_ingest.client import ExportClientError


class FixtureExportClient:
    """Serve packets from memory and/or ``campaign_{id}_packet.json`` files."""

    def __init__(
        self,
        packets: dict[int, PlatformExportPacket] | None = None,
        *,
        directory: Path | str | None = None,
    ) -> None:
        self._packets = dict(packets or {})
        self._directory = Path(directory) if directory is not None else None

    def put(self, packet: PlatformExportPacket) -> None:
        self._packets[packet.campaign_id] = packet

    async def fetch_campaign_packet(self, campaign_id: int) -> PlatformExportPacket:
        if campaign_id in self._packets:
            return self._packets[campaign_id]

        if self._directory is not None:
            path = self._directory / f"campaign_{campaign_id}_packet.json"
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                packet = PlatformExportPacket.model_validate(raw)
                self._packets[campaign_id] = packet
                return packet

        raise ExportClientError(
            f"No fixture export packet for campaign_id={campaign_id}"
        )
