"""Tests for request_logger middleware."""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient

from conftest import api_headers


@pytest.mark.asyncio
async def test_request_id_generated(http_client: AsyncClient):
    response = await http_client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-Id")


@pytest.mark.asyncio
async def test_request_id_echoed(http_client: AsyncClient):
    response = await http_client.get(
        "/health",
        headers={"X-Request-Id": "test-req-123"},
    )
    assert response.headers.get("X-Request-Id") == "test-req-123"


@pytest.mark.asyncio
async def test_health_probe_not_access_logged(http_client: AsyncClient, caplog):
    caplog.set_level(logging.INFO, logger="contenthub.access")
    await http_client.get("/health/live")
    access_logs = [r for r in caplog.records if r.name == "contenthub.access"]
    assert access_logs == []


@pytest.mark.asyncio
async def test_public_route_is_access_logged(client: AsyncClient, caplog):
    caplog.set_level(logging.INFO, logger="contenthub.access")
    response = await client.get("/api/public/kols", headers=api_headers())
    assert response.status_code == 200

    access_logs = [r for r in caplog.records if r.name == "contenthub.access"]
    assert len(access_logs) == 1
    record = access_logs[0]
    assert record.getMessage() == "request complete"
    assert record.method == "GET"
    assert record.path == "/api/public/kols"
    assert record.status_code == 200
    assert "duration_ms" in record.__dict__
