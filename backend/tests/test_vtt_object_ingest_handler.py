"""Unit tests for sync/jobs/vtt_object_ingest handler."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.export_ingest.transcript_s3 import TranscriptStoreError
from services.export_ingest.vtt_object import VttObjectResult

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_ROOT = REPO_ROOT / "sync"
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for entry in (str(BACKEND_SRC), str(SYNC_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


@pytest.fixture(scope="module")
def load_handler():
    path = SYNC_ROOT / "jobs" / "vtt_object_ingest" / "handler.py"
    spec = importlib.util.spec_from_file_location("vtt_object_ingest_handler", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_iter_s3_keys_url_decodes(load_handler):
    event = {
        "Records": [
            {
                "s3": {
                    "object": {
                        "key": "zoom-recordings/clprogvtt/m-1/f%2D1.vtt",
                    }
                }
            }
        ]
    }
    assert list(load_handler._iter_s3_keys(event)) == [
        "zoom-recordings/clprogvtt/m-1/f-1.vtt"
    ]
    assert list(load_handler._iter_s3_keys({})) == []


@pytest.mark.asyncio
async def test_run_applies_each_record(load_handler):
    settings = MagicMock()
    settings.platform_export_transcript_bucket = "cht-dev-session-assets"
    settings.aws_region = "us-east-1"

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()

    event = {
        "Records": [
            {"s3": {"object": {"key": "zoom-recordings/clprogvtt/m/f.vtt"}}}
        ]
    }
    applied = VttObjectResult(
        key="zoom-recordings/clprogvtt/m/f.vtt",
        status="applied",
        session_id=9,
    )

    with (
        patch("config.get_settings", return_value=settings),
        patch("database.async_session_maker", return_value=session),
        patch(
            "services.export_ingest.vtt_object.apply_vtt_object",
            new_callable=AsyncMock,
            return_value=applied,
        ) as apply,
        patch("services.export_ingest.transcript_s3.S3TranscriptStore") as store_cls,
    ):
        result = await load_handler._run(event)

    store_cls.assert_called_once()
    apply.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert result["status"] == "ok"
    assert result["job"] == "vtt_object_ingest"
    assert result["processed"] == 1
    assert result["results"][0]["sessionId"] == 9


@pytest.mark.asyncio
async def test_run_raises_when_bucket_missing(load_handler):
    settings = MagicMock()
    settings.platform_export_transcript_bucket = ""

    with (
        patch("config.get_settings", return_value=settings),
        pytest.raises(RuntimeError, match="PLATFORM_EXPORT_TRANSCRIPT_BUCKET"),
    ):
        await load_handler._run({})


@pytest.mark.asyncio
async def test_run_propagates_get_object_failure(load_handler):
    settings = MagicMock()
    settings.platform_export_transcript_bucket = "cht-dev-session-assets"
    settings.aws_region = "us-east-1"
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    event = {
        "Records": [
            {"s3": {"object": {"key": "zoom-recordings/clprogvtt/m/f.vtt"}}}
        ]
    }

    with (
        patch("config.get_settings", return_value=settings),
        patch("database.async_session_maker", return_value=session),
        patch(
            "services.export_ingest.transcript_s3.S3TranscriptStore",
        ),
        patch(
            "services.export_ingest.vtt_object.apply_vtt_object",
            new_callable=AsyncMock,
            side_effect=TranscriptStoreError("denied"),
        ),
        pytest.raises(TranscriptStoreError),
    ):
        await load_handler._run(event)
