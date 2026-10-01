"""CPR-13 — platform Zoom export payload DTOs (Hub ingest contract).

Path-agnostic: fixture JSON or CPR-28 live input-packet both normalize to
these models before warehouse upsert.

Field alignment notes
---------------------
* ``platform_tool_program_id`` is Platform ``Program.id`` (cuid TEXT).
* ``campaign_id`` on the wire may be a Hub **string code** (e.g.
  ``AZ-25-01_LIV001`` per CPR-28). Ingest rewrites to Hub integer
  ``campaigns.id`` before warehouse FK writes.
* Zoom: ``zoom_meeting_id`` + ``zoom_uuid`` (live sends ``zoomMeetingUuid``).
* Transcript: ``transcript_s3_key`` + ``transcript_status`` (ok|missing);
  Hub GetObject + VTT strip fills ``transcript_text``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

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
    campaign_id: str | int | None = None
    kind: str | None = None
    title: str | None = None
    session_date: datetime | None = None
    zoom_meeting_id: str | None = None
    zoom_uuid: str | None = None
    transcript_s3_key: str | None = None
    transcript_text: str | None = None
    transcript_status: str | None = None
    zoom_session_ended_at: datetime | None = None
    chm_program_id: str | None = None

    @field_validator("campaign_id", mode="before")
    @classmethod
    def _campaign_id_as_str_or_int(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        return value


class ExportAttendanceEvent(ApiModel):
    """Attendance row — fixture raw JOINED/LEFT or CPR-28 JOINED rollup."""

    platform_tool_program_id: str
    source: AttendanceSource = AttendanceSource.WEBHOOK
    event: AttendanceEventType = AttendanceEventType.JOINED
    occurred_at: datetime | None = None
    participant_email: str | None = None
    participant_name: str | None = None
    duration_seconds: int | None = None
    platform_event_id: str | None = None
    zoom_participant_id: str | None = None
    zoom_meeting_id: str | None = None
    join_time: datetime | None = None
    leave_time: datetime | None = None
    user_id: str | None = None

    @model_validator(mode="after")
    def _require_occurred_at(self) -> ExportAttendanceEvent:
        if self.occurred_at is None and self.join_time is not None:
            self.occurred_at = self.join_time
        if self.occurred_at is None:
            raise ValueError("occurred_at or join_time is required")
        return self


class ExportSurveyResponse(ApiModel):
    """Flattened survey response row (fixture or CPR-28 nested surveys)."""

    platform_tool_program_id: str | None = None
    campaign_id: str | int | None = None
    respondent_id: str | None = None
    source: str = "unknown"
    survey_type: str | None = None
    submitted_at: datetime | None = None
    submission_id: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict)


class PlatformExportPacket(ApiModel):
    """Canonical bulk payload Hub ETL consumes."""

    campaign_id: str | int
    sessions: list[ExportSession] = Field(default_factory=list)
    attendance: list[ExportAttendanceEvent] = Field(default_factory=list)
    survey_responses: list[ExportSurveyResponse] = Field(default_factory=list)
    input_completeness: dict[str, ExportSourceCompleteness] = Field(
        default_factory=dict
    )

    @field_validator("campaign_id", mode="before")
    @classmethod
    def _require_campaign_id(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError("campaign_id is required")
        return value


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
