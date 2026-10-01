"""Unit tests for sync/jobs/platform_export_ingest handler (Phase G)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_ROOT = REPO_ROOT / "sync"
BACKEND_SRC = REPO_ROOT / "backend" / "src"
for entry in (str(BACKEND_SRC), str(SYNC_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from services.export_ingest.ingest import (  # noqa: E402
    BatchIngestResult,
    CampaignIngestResult,
    ExportIngestConfigError,
    ExportIngestRuntime,
)


@pytest.fixture(scope="module")
def load_handler():
    """Load sync handler by path — backend/src/jobs would otherwise shadow it."""
    path = SYNC_ROOT / "jobs" / "platform_export_ingest" / "handler.py"
    spec = importlib.util.spec_from_file_location(
        "platform_export_ingest_handler", path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_event_direct_and_sqs(load_handler):
    assert load_handler._parse_event(None) == {}
    assert load_handler._parse_event({"limit": 3}) == {"limit": 3}
    wrapped = {
        "Records": [{"body": '{"campaignIds": [1], "source": "fixture"}'}]
    }
    assert load_handler._parse_event(wrapped) == {
        "campaignIds": [1],
        "source": "fixture",
    }


@pytest.mark.asyncio
async def test_run_returns_error_when_misconfigured(load_handler):
    settings = MagicMock()
    with (
        patch("config.get_settings", return_value=settings),
        patch(
            "services.export_ingest.ingest.resolve_export_ingest_runtime",
            side_effect=ExportIngestConfigError("missing base url"),
        ),
    ):
        result = await load_handler._run({"source": "http"})

    assert result["status"] == "error"
    assert result["job"] == "platform_export_ingest"
    assert "missing base url" in result["error"]


@pytest.mark.asyncio
async def test_run_batch_ok(load_handler):
    settings = MagicMock()
    runtime = ExportIngestRuntime(client=MagicMock(), transcript_store=None)
    batch = BatchIngestResult(
        processed=1,
        succeeded=1,
        failed=0,
        results=[
            CampaignIngestResult(
                campaign_id=42,
                status="success",
                sessions_upserted=1,
                attendance_upserted=3,
                surveys_upserted=1,
                run_id=7,
            )
        ],
    )

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()

    with (
        patch("config.get_settings", return_value=settings),
        patch(
            "services.export_ingest.ingest.resolve_export_ingest_runtime",
            return_value=runtime,
        ),
        patch("database.async_session_maker", return_value=session),
        patch(
            "services.export_ingest.ingest.ingest_campaigns_batch",
            new_callable=AsyncMock,
            return_value=batch,
        ) as ingest_batch,
    ):
        result = await load_handler._run(
            {"campaignIds": [42], "limit": 10, "source": "fixture"}
        )

    ingest_batch.assert_awaited_once()
    kwargs = ingest_batch.await_args.kwargs
    assert kwargs["campaign_ids"] == [42]
    assert kwargs["limit"] == 10
    assert kwargs["trigger"] == "schedule"
    session.commit.assert_awaited_once()

    assert result["status"] == "ok"
    assert result["processed"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["campaignId"] == 42
    assert result["results"][0]["runId"] == 7


@pytest.mark.asyncio
async def test_run_partial_when_failures(load_handler):
    settings = MagicMock()
    runtime = ExportIngestRuntime(client=MagicMock())
    batch = BatchIngestResult(
        processed=2,
        succeeded=1,
        failed=1,
        results=[
            CampaignIngestResult(campaign_id=1, status="success", run_id=1),
            CampaignIngestResult(
                campaign_id=2, status="error", error="boom"
            ),
        ],
    )
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()

    with (
        patch("config.get_settings", return_value=settings),
        patch(
            "services.export_ingest.ingest.resolve_export_ingest_runtime",
            return_value=runtime,
        ),
        patch("database.async_session_maker", return_value=session),
        patch(
            "services.export_ingest.ingest.ingest_campaigns_batch",
            new_callable=AsyncMock,
            return_value=batch,
        ),
    ):
        result = await load_handler._run({})

    assert result["status"] == "partial"
    assert result["failed"] == 1
