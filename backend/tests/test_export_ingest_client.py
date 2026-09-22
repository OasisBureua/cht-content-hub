"""Phase E: fixture + HTTP export client tests (MockTransport, no live API)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from config import Settings
from schemas.platform_export import PlatformExportPacket
from services.export_ingest.client import ExportClientError
from services.export_ingest.client_fixture import FixtureExportClient
from services.export_ingest.client_http import (
    ExportHttpMode,
    HttpExportClient,
    build_http_export_client,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"


def _fixture_packet() -> dict:
    return json.loads(
        (FIXTURES / "campaign_42_packet.json").read_text(encoding="utf-8")
    )


@pytest.mark.asyncio
async def test_fixture_client_loads_from_directory():
    client = FixtureExportClient(directory=FIXTURES)
    packet = await client.fetch_campaign_packet(42)
    assert packet.campaign_id == 42
    assert len(packet.sessions) == 1


@pytest.mark.asyncio
async def test_fixture_client_missing_campaign():
    client = FixtureExportClient(directory=FIXTURES)
    with pytest.raises(ExportClientError, match="campaign_id=999"):
        await client.fetch_campaign_packet(999)


@pytest.mark.asyncio
async def test_fixture_client_in_memory_put():
    packet = PlatformExportPacket.model_validate(
        {"campaignId": 3, "sessions": [], "attendance": []}
    )
    client = FixtureExportClient()
    client.put(packet)
    assert (await client.fetch_campaign_packet(3)).campaign_id == 3


@pytest.mark.asyncio
async def test_http_input_packet_mode():
    packet = _fixture_packet()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer test-token"
        assert request.headers.get("X-Request-Id")
        assert request.url.path.endswith(
            "/api/export/reports/campaigns/42/input-packet"
        )
        return httpx.Response(200, json=packet)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://platform.test"
    ) as http:
        client = HttpExportClient(
            "https://platform.test",
            mode=ExportHttpMode.INPUT_PACKET,
            client=http,
            bearer_token="test-token",
        )
        result = await client.fetch_campaign_packet(42)

    assert result.campaign_id == 42
    assert result.sessions[0].zoom_meeting_id == "81234567890"


@pytest.mark.asyncio
async def test_http_m2m_token_then_input_packet():
    packet = _fixture_packet()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "m2m-token"})
        assert request.headers.get("Authorization") == "Bearer m2m-token"
        return httpx.Response(200, json=packet)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://platform.test"
    ) as http:
        client = HttpExportClient(
            "https://platform.test",
            client=http,
            token_url="https://platform.test/oauth2/token",
            client_id="hub-export",
            client_secret="secret",
        )
        result = await client.fetch_campaign_packet(42)

    assert result.campaign_id == 42
    assert any(s.startswith("POST ") for s in seen)
    assert any("input-packet" in s for s in seen)


@pytest.mark.asyncio
async def test_http_v1_assembles_three_gets():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.url.path}?{request.url.query.decode()}")
        if request.url.path.endswith("/api/export/v1/sessions"):
            return httpx.Response(
                200,
                json={
                    "sessions": [
                        {
                            "platformToolProgramId": "prog1",
                            "campaignId": 5,
                            "title": "Session",
                            "zoomMeetingId": "111",
                            "zoomUuid": "u1",
                        }
                    ]
                },
            )
        if request.url.path.endswith("/api/export/v1/attendance"):
            assert b"sessionId=prog1" in request.url.query
            return httpx.Response(
                200,
                json={
                    "attendance": [
                        {
                            "platformToolProgramId": "prog1",
                            "source": "WEBHOOK",
                            "event": "JOINED",
                            "occurredAt": "2026-08-15T17:00:00Z",
                            "platformEventId": "e1",
                        }
                    ]
                },
            )
        if request.url.path.endswith("/api/export/v1/surveys"):
            return httpx.Response(200, json={"surveyResponses": []})
        return httpx.Response(404, json={"error": "unexpected"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://platform.test"
    ) as http:
        client = HttpExportClient(
            "https://platform.test",
            mode=ExportHttpMode.V1,
            client=http,
            bearer_token="tok",
        )
        packet = await client.fetch_campaign_packet(5)

    assert packet.campaign_id == 5
    assert len(packet.sessions) == 1
    assert len(packet.attendance) == 1
    assert any("/api/export/v1/sessions" in c for c in calls)
    assert any("/api/export/v1/attendance" in c for c in calls)
    assert any("/api/export/v1/surveys" in c for c in calls)


@pytest.mark.asyncio
async def test_http_requires_auth_config():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
        base_url="https://platform.test",
    ) as http:
        client = HttpExportClient("https://platform.test", client=http)
        with pytest.raises(ExportClientError, match="M2M is not configured"):
            await client.fetch_campaign_packet(1)


def test_build_http_export_client_from_settings_fields():
    settings = Settings(
        platform_export_base_url="https://platform.test",
        platform_export_http_mode="v1",
    )
    client = build_http_export_client(
        base_url=settings.platform_export_base_url,
        mode=settings.platform_export_http_mode,
        token_url=settings.platform_export_token_url,
        client_id=settings.platform_export_client_id,
        client_secret=settings.platform_export_client_secret,
        export_scope=settings.platform_export_scope,
        bearer_token="x",
    )
    assert client.mode is ExportHttpMode.V1
    assert client.base_url == "https://platform.test"


def test_settings_export_defaults():
    settings = Settings()
    assert settings.platform_export_base_url == ""
    assert settings.platform_export_http_mode == "input_packet"
    assert settings.platform_export_scope == "platform/export.read"
