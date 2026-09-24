"""Normalize platform export JSON (fixture or CPR-28 live) → PlatformExportPacket.

Keeps a single ingest path: clients always hand mappers a canonical packet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from schemas.platform_export import (
    AttendanceEventType,
    AttendanceSource,
    ExportAttendanceEvent,
    ExportSession,
    ExportSurveyResponse,
    PlatformExportPacket,
)


def coerce_campaign_id(value: Any) -> str:
    """Export campaign ids are strings on platform (e.g. AZ-25-01_LIV001)."""
    if value is None:
        return ""
    return str(value).strip()


def normalize_export_payload(raw: dict[str, Any]) -> PlatformExportPacket:
    """Accept fixture-shaped or CPR-28 live-shaped JSON."""
    data = dict(raw)
    data["sessions"] = [
        _normalize_session(item) for item in _as_list(data.get("sessions"))
    ]
    data["attendance"] = [
        _normalize_attendance(item) for item in _as_list(data.get("attendance"))
    ]

    surveys = data.get("surveyResponses")
    if surveys is None:
        surveys = data.get("surveys")
    data["surveyResponses"] = _flatten_surveys(_as_list(surveys))
    data.pop("surveys", None)

    # Drop live-only envelope fields pydantic would ignore (extra=ignore on ApiModel?).
    return PlatformExportPacket.model_validate(data)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise ValueError(f"Expected list, got {type(value).__name__}")


def _normalize_session(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("session row must be an object")
    row = dict(item)
    # CPR-28 uses zoomMeetingUuid; fixtures used zoomUuid.
    if row.get("zoomUuid") is None and row.get("zoomMeetingUuid") is not None:
        row["zoomUuid"] = row.get("zoomMeetingUuid")
    return row


def _normalize_attendance(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("attendance row must be an object")
    row = dict(item)
    # CPR-28 ships JOINED rollups without event/occurredAt.
    if row.get("event") is None:
        row["event"] = AttendanceEventType.JOINED.value
    if row.get("occurredAt") is None and row.get("joinTime") is not None:
        row["occurredAt"] = row["joinTime"]
    if row.get("source") is None:
        row["source"] = AttendanceSource.WEBHOOK.value
    # Validate source against enum; REPORT_IMPORT etc. already match.
    return row


def _flatten_surveys(items: list[Any]) -> list[dict[str, Any]]:
    """Fixture: flat surveyResponses. CPR-28: nested surveys[].responses[]."""
    flat: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nested = item.get("responses")
        if isinstance(nested, list):
            program_id = item.get("platformToolProgramId")
            campaign_id = item.get("campaignId")
            survey_type = item.get("type") or item.get("surveyType")
            survey_id = item.get("surveyId")
            source = item.get("source") or "platform"
            for idx, resp in enumerate(nested):
                if not isinstance(resp, dict):
                    continue
                submission = resp.get("submissionId")
                if not submission and survey_id:
                    submission = f"{survey_id}:{resp.get('userId', '')}:{idx}"
                flat.append(
                    {
                        "platformToolProgramId": program_id,
                        "campaignId": campaign_id,
                        "respondentId": resp.get("userId") or resp.get("respondentId"),
                        "source": source,
                        "surveyType": survey_type,
                        "submittedAt": resp.get("submittedAt"),
                        "submissionId": submission,
                        "answers": resp.get("answers") or {},
                    }
                )
        else:
            flat.append(item)
    return flat


def rewrite_packet_hub_campaign_id(
    packet: PlatformExportPacket,
    hub_campaign_id: int,
) -> PlatformExportPacket:
    """Hub warehouse FKs use integer campaigns.id; export API uses string codes."""
    return packet.model_copy(
        update={
            "campaign_id": hub_campaign_id,
            "sessions": [
                s.model_copy(update={"campaign_id": hub_campaign_id})
                for s in packet.sessions
            ],
            "survey_responses": [
                s.model_copy(update={"campaign_id": hub_campaign_id})
                for s in packet.survey_responses
            ],
        }
    )


def should_fetch_transcript(session: ExportSession) -> bool:
    """CPR-28: only GetObject when status is ok (or legacy fixtures omit status)."""
    if session.transcript_text:
        return False
    if not session.transcript_s3_key:
        return False
    status = (session.transcript_status or "").strip().lower()
    if status == "missing":
        return False
    return status in ("", "ok")
