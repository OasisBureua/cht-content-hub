"""CPR-13 Zoom export ingest (Content Hub warehouse).

* ``schemas.platform_export`` — inbound DTOs (Phase A)
* ``mappers`` — packet → warehouse field dicts + dedupe keys (Phase C)
* ``upsert`` / ``ingest_packet`` — idempotent ETL (Phase C)
* ``vtt`` / ``transcript_s3`` — cue strip + GetObject (Phase D)
* ``client_*`` — fixture + HTTP export clients (Phase E)
* ``ingest`` — campaign orchestration + admin trigger support (Phase F)
"""

from __future__ import annotations

from schemas.platform_export import (
    AttendanceEventType,
    AttendanceSource,
    ExportAttendanceEvent,
    ExportSession,
    ExportSurveyResponse,
    PlatformExportPacket,
)
from services.export_ingest.client import ExportClient, ExportClientError
from services.export_ingest.client_fixture import FixtureExportClient
from services.export_ingest.client_http import (
    ExportHttpMode,
    HttpExportClient,
    build_http_export_client,
)
from services.export_ingest.ingest import (
    ExportIngestRuntime,
    ingest_campaign,
    memory_runtime_for_tests,
    resolve_export_ingest_runtime,
)
from services.export_ingest.mappers import (
    attendance_dedupe_key,
    map_attendance,
    map_session,
    map_survey,
    survey_dedupe_key,
)
from services.export_ingest.transcript_s3 import (
    MemoryTranscriptStore,
    S3TranscriptStore,
    TranscriptStore,
    TranscriptStoreError,
)
from services.export_ingest.upsert import (
    IngestCounts,
    enrich_session_transcript,
    ingest_packet,
    upsert_packet,
)
from services.export_ingest.vtt import strip_vtt
from services.export_ingest.vtt_object import (
    VttObjectResult,
    apply_vtt_object,
    decode_object_key,
    parse_vtt_object_key,
    stripped_text_hash,
)

__all__ = [
    "AttendanceEventType",
    "AttendanceSource",
    "ExportAttendanceEvent",
    "ExportClient",
    "ExportClientError",
    "ExportHttpMode",
    "ExportIngestRuntime",
    "ExportSession",
    "ExportSurveyResponse",
    "FixtureExportClient",
    "HttpExportClient",
    "IngestCounts",
    "MemoryTranscriptStore",
    "PlatformExportPacket",
    "S3TranscriptStore",
    "TranscriptStore",
    "TranscriptStoreError",
    "VttObjectResult",
    "apply_vtt_object",
    "attendance_dedupe_key",
    "decode_object_key",
    "parse_vtt_object_key",
    "stripped_text_hash",
    "build_http_export_client",
    "enrich_session_transcript",
    "ingest_campaign",
    "ingest_packet",
    "map_attendance",
    "map_session",
    "map_survey",
    "memory_runtime_for_tests",
    "resolve_export_ingest_runtime",
    "strip_vtt",
    "survey_dedupe_key",
    "upsert_packet",
]
