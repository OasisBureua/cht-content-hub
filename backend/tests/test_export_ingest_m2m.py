"""M2M Secrets Manager resolution for CPR-11 export credentials."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.export_ingest.m2m_secrets import resolve_m2m_settings_fields


def test_resolve_m2m_uses_explicit_env_over_secret():
    with patch(
        "services.export_ingest.m2m_secrets.load_m2m_secret_dict"
    ) as load:
        token_url, client_id, client_secret, scope = resolve_m2m_settings_fields(
            secret_arn="arn:aws:secretsmanager:us-east-1:1:secret:x",
            token_url="https://auth.example/oauth2/token",
            client_id="from-env",
            client_secret="from-env-secret",
            scope="platform/export.read",
        )
        load.assert_not_called()
    assert token_url == "https://auth.example/oauth2/token"
    assert client_id == "from-env"
    assert client_secret == "from-env-secret"
    assert scope == "platform/export.read"


def test_resolve_m2m_fills_gaps_from_secrets_manager():
    secret = {
        "client_id": "hub-export",
        "client_secret": "sm-secret",
        "token_url": "https://cognito.example/oauth2/token",
        "scope": "platform/export.read",
    }
    with patch(
        "services.export_ingest.m2m_secrets.load_m2m_secret_dict",
        return_value=secret,
    ) as load:
        token_url, client_id, client_secret, scope = resolve_m2m_settings_fields(
            secret_arn="arn:aws:secretsmanager:us-east-1:1:secret:cht-dev",
            token_url="",
            client_id="",
            client_secret="",
            scope="platform/export.read",
        )
        load.assert_called_once()
    assert token_url == "https://cognito.example/oauth2/token"
    assert client_id == "hub-export"
    assert client_secret == "sm-secret"
    assert scope == "platform/export.read"


def test_resolve_m2m_partial_env_fills_secret_only():
    secret = {
        "client_id": "hub-export",
        "client_secret": "sm-secret",
        "token_url": "https://cognito.example/oauth2/token",
        "scope": "platform/export.read",
    }
    with patch(
        "services.export_ingest.m2m_secrets.load_m2m_secret_dict",
        return_value=secret,
    ):
        token_url, client_id, client_secret, scope = resolve_m2m_settings_fields(
            secret_arn="arn:aws:secretsmanager:us-east-1:1:secret:cht-dev",
            token_url="https://override/token",
            client_id="env-client",
            client_secret="",
            scope="platform/export.read",
        )
    assert token_url == "https://override/token"
    assert client_id == "env-client"
    assert client_secret == "sm-secret"


def test_resolve_m2m_raises_when_secret_load_fails():
    with patch(
        "services.export_ingest.m2m_secrets.load_m2m_secret_dict",
        side_effect=RuntimeError("AccessDenied"),
    ):
        with pytest.raises(RuntimeError, match="AccessDenied"):
            resolve_m2m_settings_fields(
                secret_arn="arn:aws:secretsmanager:us-east-1:1:secret:x",
                token_url="",
                client_id="",
                client_secret="",
            )
