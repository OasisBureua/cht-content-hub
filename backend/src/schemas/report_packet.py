"""Report-packet API schema — cht-reports' generate-time data contract.

cht-reports calls GET /api/admin/campaigns/{id}/report-packet at report
generation time. This is a different consumer and contract than the
campaigns.py UI schemas: cht-reports wants warehouse snapshots (rows +
files), not a pre-computed report-ready view.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from schemas.campaigns import ApiModel


class SourceStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    ERROR = "error"


class SourceCompletenessOut(ApiModel):
    fetched_at: datetime | None = None
    row_count: int = 0
    status: SourceStatus


class ReportPacketSessionOut(ApiModel):
    platform_tool_program_id: str | None = None
    kind: str | None = None
    title: str | None = None
    session_date: datetime | None = None
    zoom_meeting_uuid: str | None = None
    transcript_text: str


class ReportPacketSurveyOut(ApiModel):
    respondent_id: str | None = None
    source: str
    survey_type: str | None = None
    submitted_at: datetime | None = None
    answers: dict[str, Any]


class ReportPacketPlatformSliceOut(ApiModel):
    platform: str
    fetch_date: date
    status: str
    row_count: int | None = None
    rows: list[dict[str, Any]]
    synced_at: datetime | None = None


class ReportInputPacketOut(ApiModel):
    campaign_id: int
    campaign_name: str
    window_start: date | None = None
    window_end: date | None = None
    sources: list[str]
    hubspot_raw_data: Any | None = None
    platform_slices: list[ReportPacketPlatformSliceOut]
    sessions: list[ReportPacketSessionOut]
    survey_responses: list[ReportPacketSurveyOut]
    input_completeness: dict[str, SourceCompletenessOut]
