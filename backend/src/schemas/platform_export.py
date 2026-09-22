"""CPR-13 — platform Zoom export payload DTOs (Hub ingest contract).

These models describe what Content Hub *consumes* from cht-platform-tool's
export API. They are intentionally HTTP-path agnostic: the live client may
call a single input-packet endpoint or CPR-12's versioned GETs
(`/api/export/v1/sessions|attendance|surveys`). Mappers and warehouse
upserts should depend on these DTOs, not on URL strings.

Field alignment notes
---------------------
* ``platform_tool_program_id`` is Platform ``Program.id`` (cuid TEXT), never
  an integer FK into Hub.
* ``campaign_id`` is Hub ``campaigns.id``. Platform will set
  ``Program.campaignId`` (CPR-12); until then fixtures may supply it.
* Zoom IDs are stored as two optional fields — ``zoom_meeting_id``
  (``Program.zoomMeetingId`` / session meeting id) and ``zoom_uuid``
  (``ZoomRecordingSession.zoomUuid``). Do not collapse them into one
  ``zoom_meeting_uuid`` column at ingest time.
* Transcript: hedge both ``transcript_s3_key`` (raw WebVTT on platform S3)
  and ``transcript_text`` (filled after Hub strips cues on ingest).
* Session fields that Sebastian's report-packet later exposes
  (``platform_tool_program_id``, ``kind``, ``title``, ``session_date``,
  ``transcript_text``) use the same snake_case names so warehouse →
  report-packet mapping stays 1:1 when Phase H lands.

Out of scope here: Hub report-packet *response* schemas (see
``schemas/report_packet.py`` on Sebastian's branch), Cognito M2M, and
Zoom API calls.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from schemas.campaigns import ApiModel


class AttendanceEventType(StrEnum):
    JOINED = "JOINED"
    LEFT = "LEFT"


class AttendanceSource(StrEnum):
    WEBHOOK = "WEBHOOK"
    MEETING_SDK = "MEETING_SDK"
    REPORT_IMPORT = "REPORT_IMPORT"


class SourceCompletenessStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    ERROR = "error"


class ExportSourceCompleteness(ApiModel):
    """Per-source completeness block inside an export packet."""

    fetched_at: datetime | None = None
    row_count: int = 0
    status: SourceCompletenessStatus = SourceCompletenessStatus.MISSING
    error: str | None = None


class ExportSession(ApiModel):
    """One Zoom-backed program/session row from the platform export."""

    platform_tool_program_id: str
    campaign_id: int | None = None
    kind: str | None = None
    title: str | None = None
    session_date: datetime | None = None
    zoom_meeting_id: str | None = None
    zoom_uuid: str | None = None
    transcript_s3_key: str | None = None
    transcript_text: str | None = None
    zoom_session_ended_at: datetime | None = None


class ExportAttendanceEvent(ApiModel):
    """One raw JOINED/LEFT (or import) attendance event."""

    platform_tool_program_id: str
    source: AttendanceSource
    event: AttendanceEventType
    occurred_at: datetime
    participant_email: str | None = None
    participant_name: str | None = None
    duration_seconds: int | None = None
    # Optional identity fields for idempotent upserts once export includes them.
    platform_event_id: str | None = None
    zoom_participant_id: str | None = None
    zoom_meeting_id: str | None = None
    join_time: datetime | None = None
    leave_time: datetime | None = None


class ExportSurveyResponse(ApiModel):
    """CPR-14 adjacency — typed so sessions/attendance are not blocked.

    Warehouse persistence for surveys is out of scope for CPR-13 v1 beyond
    accepting the field on the packet.
    """

    platform_tool_program_id: str | None = None
    campaign_id: int | None = None
    respondent_id: str | None = None
    source: str = "unknown"
    survey_type: str | None = None
    submitted_at: datetime | None = None
    submission_id: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict)


class PlatformExportPacket(ApiModel):
    """Canonical bulk payload Hub ETL consumes (path-agnostic).

    Whether the HTTP client fetched one blob or assembled three GETs, the
    ingest orchestrator always normalizes to this shape before mapping.
    """

    campaign_id: int
    sessions: list[ExportSession] = Field(default_factory=list)
    attendance: list[ExportAttendanceEvent] = Field(default_factory=list)
    survey_responses: list[ExportSurveyResponse] = Field(default_factory=list)
    input_completeness: dict[str, ExportSourceCompleteness] = Field(
        default_factory=dict
    )


class ExportIngestRunOut(ApiModel):
    """Admin response for ``POST .../export-ingest``."""

    id: int
    campaign_id: int | None = None
    trigger: str
    status: str
    sessions_upserted: int = 0
    attendance_upserted: int = 0
    surveys_upserted: int = 0
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
