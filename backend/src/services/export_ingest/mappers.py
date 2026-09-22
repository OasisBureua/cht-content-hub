"""Pure mappers: platform export DTOs → warehouse field dicts.

No DB or HTTP. Dedupe keys are stable so repeated ingest is idempotent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from schemas.platform_export import (
    ExportAttendanceEvent,
    ExportSession,
    ExportSurveyResponse,
)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is not None:
        return value.isoformat().replace("+00:00", "Z")
    return f"{value.isoformat()}Z"


def attendance_dedupe_key(event: ExportAttendanceEvent) -> str:
    """Prefer platform event id; else a natural composite key."""
    if event.platform_event_id:
        return f"platform_event:{event.platform_event_id}"
    email = (event.participant_email or "").strip().lower()
    participant = event.zoom_participant_id or ""
    join = _iso(event.join_time)
    return "|".join(
        [
            event.platform_tool_program_id,
            event.source.value,
            event.event.value,
            _iso(event.occurred_at),
            email,
            participant,
            join,
        ]
    )


def survey_dedupe_key(row: ExportSurveyResponse) -> str:
    if row.submission_id:
        return f"submission:{row.submission_id}"
    submitted = _iso(row.submitted_at)
    return "|".join(
        [
            row.platform_tool_program_id or "",
            row.respondent_id or "",
            row.source,
            submitted,
        ]
    )


def map_session(
    session: ExportSession,
    *,
    default_campaign_id: int | None = None,
) -> dict[str, Any]:
    campaign_id = (
        session.campaign_id
        if session.campaign_id is not None
        else default_campaign_id
    )
    return {
        "platform_tool_program_id": session.platform_tool_program_id,
        "campaign_id": campaign_id,
        "kind": session.kind,
        "title": session.title,
        "session_date": session.session_date,
        "zoom_meeting_id": session.zoom_meeting_id,
        "zoom_uuid": session.zoom_uuid,
        "transcript_s3_key": session.transcript_s3_key,
        "transcript_text": session.transcript_text,
        "zoom_session_ended_at": session.zoom_session_ended_at,
    }


def map_attendance(
    event: ExportAttendanceEvent,
    *,
    default_campaign_id: int | None = None,
) -> dict[str, Any]:
    return {
        "dedupe_key": attendance_dedupe_key(event),
        "platform_tool_program_id": event.platform_tool_program_id,
        "campaign_id": default_campaign_id,
        "source": event.source.value,
        "event": event.event.value,
        "occurred_at": event.occurred_at,
        "participant_email": event.participant_email,
        "participant_name": event.participant_name,
        "duration_seconds": event.duration_seconds,
        "platform_event_id": event.platform_event_id,
        "zoom_participant_id": event.zoom_participant_id,
        "zoom_meeting_id": event.zoom_meeting_id,
        "join_time": event.join_time,
        "leave_time": event.leave_time,
    }


def map_survey(
    row: ExportSurveyResponse,
    *,
    default_campaign_id: int | None = None,
) -> dict[str, Any]:
    campaign_id = (
        row.campaign_id if row.campaign_id is not None else default_campaign_id
    )
    return {
        "dedupe_key": survey_dedupe_key(row),
        "campaign_id": campaign_id,
        "platform_tool_program_id": row.platform_tool_program_id,
        "respondent_id": row.respondent_id,
        "source": row.source,
        "survey_type": row.survey_type,
        "submitted_at": row.submitted_at,
        "submission_id": row.submission_id,
        "answers": dict(row.answers or {}),
    }
