"""Tests for API error logging."""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_auth_failure_is_logged(http_client: AsyncClient, caplog):
    caplog.set_level(logging.WARNING, logger="contenthub.api")
    response = await http_client.get("/api/public/kols")
    assert response.status_code == 401

    api_logs = [r for r in caplog.records if r.name == "contenthub.api"]
    assert len(api_logs) == 1
    assert api_logs[0].error_code == "AUTH_INVALID_KEY"
    assert api_logs[0].status_code == 401


@pytest.mark.asyncio
async def test_not_found_is_logged(client: AsyncClient, caplog):
    from conftest import api_headers

    caplog.set_level(logging.WARNING, logger="contenthub.api")
    response = await client.get(
        "/api/public/kols/missing-slug",
        headers=api_headers(),
    )
    assert response.status_code == 404

    api_logs = [r for r in caplog.records if r.name == "contenthub.api"]
    assert len(api_logs) == 1
    assert api_logs[0].error_code == "RESOURCE_NOT_FOUND"
