"""Load CPR-11 M2M export credentials from AWS Secrets Manager.

Uche provisions ``cht-dev-cognito-m2m-export`` (dev) with JSON keys:
``client_id``, ``client_secret``, ``token_url``, ``scope``.

Follows the same boto3 Secrets Manager pattern as ``sync/shared/secrets.py``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def load_m2m_secret_dict(secret_id: str, *, region_name: str | None = None) -> dict[str, Any]:
    """Fetch and parse the M2M export secret JSON."""
    import boto3

    region = region_name or os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    payload = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    if not isinstance(payload, dict):
        raise ValueError(f"M2M secret {secret_id} is not a JSON object")
    return payload


def apply_m2m_secret_to_environ(secret_id: str, *, region_name: str | None = None) -> None:
    """Fill PLATFORM_EXPORT_* env vars from SM when not already set."""
    payload = load_m2m_secret_dict(secret_id, region_name=region_name)
    mapping = {
        "PLATFORM_EXPORT_CLIENT_ID": "client_id",
        "PLATFORM_EXPORT_CLIENT_SECRET": "client_secret",
        "PLATFORM_EXPORT_TOKEN_URL": "token_url",
        "PLATFORM_EXPORT_SCOPE": "scope",
    }
    loaded = False
    for env_name, key in mapping.items():
        if os.environ.get(env_name):
            continue
        value = payload.get(key, "")
        if value:
            os.environ[env_name] = str(value)
            loaded = True
    if loaded:
        log.info("Loaded PLATFORM_EXPORT M2M credentials from Secrets Manager")


def resolve_m2m_settings_fields(
    *,
    secret_arn: str = "",
    token_url: str = "",
    client_id: str = "",
    client_secret: str = "",
    scope: str = "platform/export.read",
    region_name: str | None = None,
) -> tuple[str, str, str, str]:
    """Return token_url, client_id, client_secret, scope — SM fills gaps.

    Raises ``RuntimeError`` if ``secret_arn`` is set but SM load fails and
    required fields are still missing (avoids opaque "M2M not configured").
    """
    sm_error: Exception | None = None
    if secret_arn and (not client_secret or not token_url or not client_id):
        try:
            payload = load_m2m_secret_dict(secret_arn, region_name=region_name)
        except Exception as exc:  # noqa: BLE001
            sm_error = exc
            log.warning("Failed to load M2M secret %s: %s", secret_arn, exc)
            payload = {}
        token_url = token_url or str(payload.get("token_url") or "")
        client_id = client_id or str(payload.get("client_id") or "")
        client_secret = client_secret or str(payload.get("client_secret") or "")
        scope = scope or str(payload.get("scope") or "platform/export.read")

    if secret_arn and sm_error and (not token_url or not client_id or not client_secret):
        raise RuntimeError(
            f"Failed to load PLATFORM_EXPORT_M2M_SECRET_ARN ({secret_arn}): "
            f"{sm_error}. Use AWS credentials for the secret's account, or set "
            "PLATFORM_EXPORT_TOKEN_URL / CLIENT_ID / CLIENT_SECRET in .env."
        )
    return token_url, client_id, client_secret, scope or "platform/export.read"
