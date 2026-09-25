"""Inbound Hub M2M: Bearer required, CRUD scopes enforced."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from auth.m2m import (
    crud_for_method,
    decode_access_token,
    has_required_scope,
    require_m2m_token,
    required_scope,
    token_scopes,
)
from config import Settings
from conftest import mint_test_token


def _request(method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )


def _settings() -> Settings:
    return Settings(
        hub_m2m_issuer="https://hub.test",
        hub_m2m_test_secret="test-m2m-hs256",
    )


def test_crud_scope_mapping():
    assert required_scope("catalog", "GET") == "hub/catalog.read"
    assert required_scope("admin", "POST") == "hub/admin.create"
    assert required_scope("admin", "PATCH") == "hub/admin.update"
    assert required_scope("admin", "DELETE") == "hub/admin.delete"
    assert required_scope("reports", "GET") == "hub/reports.read"
    assert required_scope("catalog", "GET", server="hub") == "hub/catalog.read"
    assert crud_for_method("PUT") == "update"


def test_has_required_scope_star_and_write():
    assert has_required_scope({"hub/catalog.read"}, "hub/catalog.read")
    assert has_required_scope({"hub/admin.*"}, "hub/admin.update")
    assert has_required_scope({"hub/admin.write"}, "hub/admin.create")
    assert not has_required_scope({"hub/admin.write"}, "hub/admin.read")
    assert not has_required_scope({"hub/catalog.read"}, "hub/admin.update")


def test_token_scopes_space_or_list():
    assert token_scopes({"scope": "hub/catalog.read hub/admin.update"}) == {
        "hub/catalog.read",
        "hub/admin.update",
    }
    assert token_scopes({"scp": ["hub/reports.read"]}) == {"hub/reports.read"}


def test_missing_bearer_rejected():
    with pytest.raises(HTTPException) as exc:
        require_m2m_token(
            _request("GET"),
            _settings(),
            resource="catalog",
            authorization=None,
        )
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing bearer token"


def test_x_api_key_is_not_accepted():
    with pytest.raises(HTTPException) as exc:
        require_m2m_token(
            _request("GET"),
            _settings(),
            resource="catalog",
            authorization=None,
        )
    assert exc.value.status_code == 401
    assert exc.value.detail == "Missing bearer token"


def test_hs256_token_accepted_and_scope_checked():
    token = mint_test_token("hub/catalog.read")
    caller = require_m2m_token(
        _request("GET"),
        _settings(),
        resource="catalog",
        authorization=f"Bearer {token}",
    )
    assert caller == "m2m:cht-test-m2m"

    with pytest.raises(HTTPException) as exc:
        require_m2m_token(
            _request("PATCH"),
            _settings(),
            resource="admin",
            authorization=f"Bearer {token}",
        )
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"


def test_invalid_bearer_rejected():
    with pytest.raises(HTTPException) as exc:
        decode_access_token("not-a-jwt", _settings())
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid bearer token"


@pytest.mark.asyncio
async def test_public_tags_bearer_ok(client):
    r = await client.get(
        "/api/public/tags",
        headers={"Authorization": f"Bearer {mint_test_token('hub/catalog.read')}"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_public_tags_bearer_wrong_scope(client):
    r = await client.get(
        "/api/public/tags",
        headers={"Authorization": f"Bearer {mint_test_token('hub/reports.read')}"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_requires_admin_scope(client):
    r = await client.get(
        "/api/admin/tagger/runs",
        headers={"Authorization": f"Bearer {mint_test_token('hub/catalog.read')}"},
    )
    assert r.status_code == 401
    assert r.json()["message"] == "Unauthorized"


@pytest.mark.asyncio
async def test_x_api_key_header_no_longer_authenticates(http_client):
    r = await http_client.get(
        "/api/public/tags",
        headers={"X-API-Key": "test-public-key"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Missing bearer token"
