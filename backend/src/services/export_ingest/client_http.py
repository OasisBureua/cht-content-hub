"""HTTP export client for cht-platform-tool (CPR-11 M2M + CPR-28 packet).

Default mode ``input_packet``:
  GET /api/export/reports/campaigns/{campaignId}/input-packet

Auth: Cognito ``client_credentials`` with HTTP Basic (client_id:client_secret),
scope ``platform/export.read``. Always sends ``X-Request-Id``.
"""

from __future__ import annotations

import base64
import time
import uuid
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import httpx

from schemas.platform_export import ExportSession, PlatformExportPacket
from services.export_ingest.client import ExportClientError
from services.export_ingest.normalize import normalize_export_payload


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
        self._token_expires_at = 0.0
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

    def _token_valid(self) -> bool:
        if not self._bearer_token:
            return False
        # Static bearer (tests) has no expiry.
        if self._token_expires_at <= 0:
            return True
        return time.time() < self._token_expires_at - 60

    async def _access_token(self, client: httpx.AsyncClient, *, force: bool = False) -> str:
        if not force and self._token_valid():
            return self._bearer_token  # type: ignore[return-value]
        if not (self.token_url and self.client_id and self.client_secret):
            # Static bearer (tests / injected token) — no refresh path.
            if self._bearer_token:
                return self._bearer_token
            raise ExportClientError(
                "Export M2M is not configured "
                "(set bearer_token or token_url + client_id + client_secret)"
            )
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        try:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "scope": self.export_scope,
                },
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if response.status_code in (401, 403):
                raise ExportClientError(
                    f"M2M token request failed with HTTP {response.status_code}"
                )
            response.raise_for_status()
            payload = response.json()
        except ExportClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExportClientError(f"M2M token request failed: {exc}") from exc
        token = payload.get("access_token")
        if not token:
            raise ExportClientError("M2M token response missing access_token")
        self._bearer_token = str(token)
        expires_in = payload.get("expires_in")
        try:
            self._token_expires_at = time.time() + float(expires_in or 3600)
        except (TypeError, ValueError):
            self._token_expires_at = time.time() + 3600
        return self._bearer_token

    async def _auth_headers(
        self, client: httpx.AsyncClient, *, force_token: bool = False
    ) -> dict[str, str]:
        token = await self._access_token(client, force=force_token)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
        }

    async def _get_json(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        client = await self._get_client()
        headers = await self._auth_headers(client)
        try:
            response = await client.get(path, params=params, headers=headers)
            if response.status_code == 401:
                # Refresh once in case of expired token.
                headers = await self._auth_headers(client, force_token=True)
                response = await client.get(path, params=params, headers=headers)
            if response.status_code in (401, 403):
                raise ExportClientError(
                    f"Export GET {path} unauthorized (HTTP {response.status_code})"
                )
            if response.status_code == 404:
                raise ExportClientError(f"Export GET {path} not found (HTTP 404)")
            if response.status_code == 400:
                raise ExportClientError(
                    f"Export GET {path} bad request (HTTP 400) — "
                    "check X-Request-Id and campaignId"
                )
            response.raise_for_status()
            return response.json()
        except ExportClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExportClientError(f"Export GET {path} failed: {exc}") from exc

    async def fetch_campaign_packet(
        self, campaign_id: str | int
    ) -> PlatformExportPacket:
        if self.mode is ExportHttpMode.INPUT_PACKET:
            return await self._fetch_input_packet(campaign_id)
        return await self._fetch_v1_assembled(campaign_id)

    async def _fetch_input_packet(
        self, campaign_id: str | int
    ) -> PlatformExportPacket:
        encoded = quote(str(campaign_id).strip(), safe="")
        path = f"/api/export/reports/campaigns/{encoded}/input-packet"
        raw = await self._get_json(path)
        if not isinstance(raw, dict):
            raise ExportClientError(
                f"Invalid input-packet payload for campaign {campaign_id}: "
                f"expected object, got {type(raw).__name__}"
            )
        try:
            return normalize_export_payload(raw)
        except Exception as exc:  # noqa: BLE001
            raise ExportClientError(
                f"Invalid input-packet payload for campaign {campaign_id}: {exc}"
            ) from exc

    async def _fetch_v1_assembled(
        self, campaign_id: str | int
    ) -> PlatformExportPacket:
        sessions_raw = await self._get_json(
            "/api/export/v1/sessions",
            params={"campaignId": str(campaign_id)},
        )
        assembled = {
            "campaignId": campaign_id,
            "sessions": _as_list(sessions_raw, "sessions"),
            "attendance": [],
            "surveyResponses": [],
        }
        session_models = [
            ExportSession.model_validate(item) for item in assembled["sessions"]
        ]
        attendance: list[Any] = []
        program_ids = {
            s.platform_tool_program_id
            for s in session_models
            if s.platform_tool_program_id
        }
        for program_id in sorted(program_ids):
            att_raw = await self._get_json(
                "/api/export/v1/attendance",
                params={"sessionId": program_id},
            )
            attendance.extend(_as_list(att_raw, "attendance"))
        assembled["attendance"] = attendance

        surveys_raw = await self._get_json(
            "/api/export/v1/surveys",
            params={"campaignId": str(campaign_id)},
        )
        # Prefer surveyResponses; fall back to surveys for CPR-28-shaped payloads.
        if isinstance(surveys_raw, dict) and "surveys" in surveys_raw:
            assembled["surveys"] = surveys_raw["surveys"]
        else:
            assembled["surveyResponses"] = _as_list(surveys_raw, "surveyResponses")

        try:
            return normalize_export_payload(assembled)
        except Exception as exc:  # noqa: BLE001
            raise ExportClientError(
                f"Invalid v1-assembled packet for campaign {campaign_id}: {exc}"
            ) from exc


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
        for key in ("items", "data", "sessions", "attendance", "surveyResponses", "surveys"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
    raise ExportClientError(
        f"Expected list or object with '{preferred_key}' list, got {type(payload).__name__}"
    )
