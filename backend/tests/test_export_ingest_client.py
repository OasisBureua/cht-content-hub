"""Phase E: fixture + HTTP export client tests (MockTransport, no live API)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from config import Settings
from schemas.platform_export import PlatformExportPacket
from services.export_ingest.client import ExportClientError
from services.export_ingest.client_fixture import FixtureExportClient
from auth.outbound import reset_shared_token_cache
from services.export_ingest.client_http import (
    ExportHttpMode,
    HttpExportClient,
    build_http_export_client,
)
from services.export_ingest.normalize import normalize_export_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "platform_export"


@pytest.fixture(autouse=True)
def _clear_outbound_token_cache():
    reset_shared_token_cache()
    yield
    reset_shared_token_cache()


def _fixture_packet() -> dict:
    return json.loads(
        (FIXTURES / "campaign_42_packet.json").read_text(encoding="utf-8")
    )


def _cpr28_packet() -> dict:
    return json.loads(
        (FIXTURES / "cpr28_live_shaped_packet.json").read_text(encoding="utf-8")
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


def test_normalize_cpr28_live_shaped_packet():
    packet = normalize_export_payload(_cpr28_packet())
    assert packet.campaign_id == "AZ-25-01_LIV001"
    assert packet.sessions[0].zoom_uuid == "AbCdEf=="
    assert packet.sessions[0].transcript_status == "ok"
    assert len(packet.attendance) == 1
    assert packet.attendance[0].event.value == "JOINED"
    assert packet.attendance[0].occurred_at is not None
    assert len(packet.survey_responses) == 1
    assert packet.survey_responses[0].respondent_id == "user_1"
    assert packet.survey_responses[0].answers["nps"] == 9


@pytest.mark.asyncio
async def test_http_input_packet_mode_string_campaign_id():
    packet = _cpr28_packet()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer test-token"
        assert request.headers.get("X-Request-Id")
        assert "/api/export/reports/campaigns/AZ-25-01_LIV001/input-packet" in str(
            request.url
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
        result = await client.fetch_campaign_packet("AZ-25-01_LIV001")

    assert result.campaign_id == "AZ-25-01_LIV001"
    assert result.sessions[0].zoom_meeting_id == "81234567890"
    assert result.sessions[0].zoom_uuid == "AbCdEf=="


@pytest.mark.asyncio
async def test_http_m2m_basic_token_then_input_packet():
    packet = _fixture_packet()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/oauth2/token"):
            auth = request.headers.get("Authorization", "")
            expected = "Basic " + base64.b64encode(b"hub-export:secret").decode()
            assert auth == expected
            return httpx.Response(
                200, json={"access_token": "m2m-token", "expires_in": 3600}
            )
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
async def test_http_401_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "unauthorized"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://platform.test"
    ) as http:
        client = HttpExportClient(
            "https://platform.test",
            client=http,
            bearer_token="bad",
        )
        with pytest.raises(ExportClientError, match="401"):
            await client.fetch_campaign_packet("AZ-25-01_LIV001")


@pytest.mark.asyncio
async def test_http_401_retries_once_with_refreshed_m2m_token():
    packet = _fixture_packet()
    calls = {"token": 0, "packet": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            calls["token"] += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok-{calls['token']}",
                    "expires_in": 3600,
                },
            )
        calls["packet"] += 1
        auth = request.headers.get("Authorization")
        if calls["packet"] == 1:
            assert auth == "Bearer tok-1"
            return httpx.Response(401, json={"message": "expired"})
        assert auth == "Bearer tok-2"
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
    assert calls["token"] == 2
    assert calls["packet"] == 2


@pytest.mark.asyncio
async def test_http_403_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://platform.test"
    ) as http:
        client = HttpExportClient(
            "https://platform.test",
            client=http,
            bearer_token="tok",
        )
        with pytest.raises(ExportClientError, match="403"):
            await client.fetch_campaign_packet("AZ-25-01_LIV001")


@pytest.mark.asyncio
async def test_http_404_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "missing"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://platform.test"
    ) as http:
        client = HttpExportClient(
            "https://platform.test",
            client=http,
            bearer_token="tok",
        )
        with pytest.raises(ExportClientError, match="404"):
            await client.fetch_campaign_packet("missing")


@pytest.mark.asyncio
async def test_http_empty_packet_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "campaignId": "AZ-25-01_LIV001",
                "sessions": [],
                "attendance": [],
                "surveys": [],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://platform.test"
    ) as http:
        client = HttpExportClient(
            "https://platform.test",
            client=http,
            bearer_token="tok",
        )
        packet = await client.fetch_campaign_packet("AZ-25-01_LIV001")

    assert packet.sessions == []
    assert packet.attendance == []
    assert packet.survey_responses == []


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
    assert settings.platform_export_m2m_secret_arn == ""
