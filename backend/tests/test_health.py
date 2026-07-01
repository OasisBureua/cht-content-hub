"""Health and actuator endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["info"]["app"]["status"] == "up"


@pytest.mark.asyncio
async def test_health_ready(client):
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert "database" in response.json()["details"]


@pytest.mark.asyncio
async def test_health_live(client):
    response = await client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["uptime"] >= 0


@pytest.mark.asyncio
async def test_health_detail(client):
    response = await client.get("/health/detail")
    assert response.status_code == 200
    body = response.json()
    assert "components" in body
    assert "application" in body


@pytest.mark.asyncio
async def test_actuator_info(client):
    response = await client.get("/actuator/info")
    assert response.status_code == 200
    body = response.json()
    assert body["app-name"] == "Content Hub API"
    assert body["service-role"] == "api"
    assert "image-tag" in body
