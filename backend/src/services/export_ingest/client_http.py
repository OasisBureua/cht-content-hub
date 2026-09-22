"""HTTP export client for cht-platform-tool (CPR-12 producer).

Supports two modes (config-driven; path ownership stays on platform-tool):

* ``input_packet`` — ``GET /api/export/reports/campaigns/{id}/input-packet``
* ``v1`` — assemble CPR-12 versioned GETs into ``PlatformExportPacket``

Auth: Cognito ``client_credentials`` with scope ``platform/export.read``
(or a pre-supplied bearer token for tests). Hub never hosts the M2M server.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

import httpx

from schemas.platform_export import (
    ExportAttendanceEvent,
    ExportSession,
    ExportSurveyResponse,
    PlatformExportPacket,
)
from services.export_ingest.client import ExportClientError


class ExportHttpMode(StrEnum):
    INPUT_PACKET = "input_packet"
    V1 = "v1"


class HttpExportClient:
    def __init__(
        self,
        base_url: str,
        *,
        mode: ExportHttpMode | str = ExportHttpMode.INPUT_PACKET,
        client: httpx.AsyncClient | None = None,
        bearer_token: str | None = None,
        token_url: str = "",
        client_id: str = "",
        client_secret: str = "",
        export_scope: str = "platform/export.read",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not base_url:
            raise ValueError("platform export base_url is required")
        self.base_url = base_url.rstrip("/")
        self.mode = ExportHttpMode(mode)
        self._client = client
        self._owns_client = client is None
        self._bearer_token = bearer_token
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.export_scope = export_scope
        self.timeout_seconds = timeout_seconds

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        return self._client

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._bearer_token:
            return self._bearer_token
        if not (self.token_url and self.client_id and self.client_secret):
            raise ExportClientError(
                "Export M2M is not configured "
                "(set bearer_token or token_url + client_id + client_secret)"
            )
        try:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": self.export_scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ExportClientError(f"M2M token request failed: {exc}") from exc
        token = payload.get("access_token")
        if not token:
            raise ExportClientError("M2M token response missing access_token")
        self._bearer_token = str(token)
        return self._bearer_token

    async def _auth_headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        token = await self._access_token(client)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
        }

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        client = await self._get_client()
        headers = await self._auth_headers(client)
        try:
            response = await client.get(path, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except ExportClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExportClientError(f"Export GET {path} failed: {exc}") from exc

    async def fetch_campaign_packet(self, campaign_id: int) -> PlatformExportPacket:
        if self.mode is ExportHttpMode.INPUT_PACKET:
            return await self._fetch_input_packet(campaign_id)
        return await self._fetch_v1_assembled(campaign_id)

    async def _fetch_input_packet(self, campaign_id: int) -> PlatformExportPacket:
        path = f"/api/export/reports/campaigns/{campaign_id}/input-packet"
        raw = await self._get_json(path)
        try:
            packet = PlatformExportPacket.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            raise ExportClientError(
                f"Invalid input-packet payload for campaign {campaign_id}: {exc}"
            ) from exc
        if packet.campaign_id != campaign_id:
            # Trust path campaign id when body omits/mismatches (defensive).
            packet = packet.model_copy(update={"campaign_id": campaign_id})
        return packet

    async def _fetch_v1_assembled(self, campaign_id: int) -> PlatformExportPacket:
        sessions_raw = await self._get_json(
            "/api/export/v1/sessions",
            params={"campaignId": campaign_id},
        )
        sessions = _as_list(sessions_raw, "sessions")
        session_models = [ExportSession.model_validate(item) for item in sessions]

        attendance_models: list[ExportAttendanceEvent] = []
        program_ids = {
            s.platform_tool_program_id for s in session_models if s.platform_tool_program_id
        }
        for program_id in sorted(program_ids):
            att_raw = await self._get_json(
                "/api/export/v1/attendance",
                params={"sessionId": program_id},
            )
            for item in _as_list(att_raw, "attendance"):
                attendance_models.append(ExportAttendanceEvent.model_validate(item))

        surveys_raw = await self._get_json(
            "/api/export/v1/surveys",
            params={"campaignId": campaign_id},
        )
        survey_models = [
            ExportSurveyResponse.model_validate(item)
            for item in _as_list(surveys_raw, "surveyResponses")
        ]

        return PlatformExportPacket(
            campaign_id=campaign_id,
            sessions=session_models,
            attendance=attendance_models,
            survey_responses=survey_models,
        )


def build_http_export_client(
    *,
    base_url: str,
    mode: str = ExportHttpMode.INPUT_PACKET.value,
    token_url: str = "",
    client_id: str = "",
    client_secret: str = "",
    export_scope: str = "platform/export.read",
    bearer_token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> HttpExportClient:
    """Construct an HTTP export client from settings-like fields."""
    return HttpExportClient(
        base_url,
        mode=mode,
        client=client,
        bearer_token=bearer_token,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        export_scope=export_scope,
    )


def _as_list(payload: Any, preferred_key: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if preferred_key in payload and isinstance(payload[preferred_key], list):
            return payload[preferred_key]
        for key in ("items", "data", "sessions", "attendance", "surveyResponses"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
    raise ExportClientError(
        f"Expected list or object with '{preferred_key}' list, got {type(payload).__name__}"
    )

