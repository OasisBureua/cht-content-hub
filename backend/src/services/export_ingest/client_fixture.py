"""Fixture / in-memory export client for offline CPR-13 development."""

from __future__ import annotations

import json
from pathlib import Path

from schemas.platform_export import PlatformExportPacket
from services.export_ingest.client import ExportClientError
from services.export_ingest.normalize import normalize_export_payload


class FixtureExportClient:
    """Serve packets from memory and/or ``campaign_{id}_packet.json`` files."""

    def __init__(
        self,
        packets: dict[str | int, PlatformExportPacket] | None = None,
        *,
        directory: Path | str | None = None,
    ) -> None:
        self._packets: dict[str, PlatformExportPacket] = {
            str(k): v for k, v in (packets or {}).items()
        }
        self._directory = Path(directory) if directory is not None else None

    def put(self, packet: PlatformExportPacket) -> None:
        self._packets[str(packet.campaign_id)] = packet

    async def fetch_campaign_packet(
        self, campaign_id: str | int
    ) -> PlatformExportPacket:
        key = str(campaign_id)
        if key in self._packets:
            return self._packets[key]

        if self._directory is not None:
            path = self._directory / f"campaign_{key}_packet.json"
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                packet = normalize_export_payload(raw)
                self._packets[key] = packet
                return packet

        raise ExportClientError(
            f"No fixture export packet for campaign_id={campaign_id}"
        )
