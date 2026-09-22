"""Load DATABASE_URL and cache secret from Secrets Manager when running in Lambda."""

from __future__ import annotations

import json
import logging
import os

import boto3

log = logging.getLogger(__name__)
_loaded = False


def ensure_lambda_secrets() -> None:
    """Populate os.environ from Secrets Manager ARNs (Lambda has no ECS-style secret refs)."""
    global _loaded
    if _loaded or not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return

    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)

    db_arn = os.environ.get("DATABASE_SECRET_ARN", "")
    if db_arn and not os.environ.get("DATABASE_URL"):
        payload = json.loads(client.get_secret_value(SecretId=db_arn)["SecretString"])
        os.environ["DATABASE_URL"] = payload["url"]
        log.info("Loaded DATABASE_URL from Secrets Manager")

    app_arn = os.environ.get("APP_SECRETS_ARN", "")
    if app_arn:
        payload = json.loads(client.get_secret_value(SecretId=app_arn)["SecretString"])
        if not os.environ.get("INTERNAL_CACHE_SECRET"):
            secret = payload.get("internal_cache_secret", "")
            if secret:
                os.environ["INTERNAL_CACHE_SECRET"] = secret
                log.info("Loaded INTERNAL_CACHE_SECRET from Secrets Manager")

        # CPR-13 M2M / export client settings (optional until CPR-12 is live).
        # Prefer env already set on the Lambda; fill gaps from app-secrets JSON.
        _export_env_from_secret = {
            "PLATFORM_EXPORT_BASE_URL": "platform_export_base_url",
            "PLATFORM_EXPORT_HTTP_MODE": "platform_export_http_mode",
            "PLATFORM_EXPORT_TOKEN_URL": "platform_export_token_url",
            "PLATFORM_EXPORT_CLIENT_ID": "platform_export_client_id",
            "PLATFORM_EXPORT_CLIENT_SECRET": "platform_export_client_secret",
            "PLATFORM_EXPORT_SCOPE": "platform_export_scope",
            "PLATFORM_EXPORT_TRANSCRIPT_BUCKET": "platform_export_transcript_bucket",
        }
        loaded_export = False
        for env_name, secret_key in _export_env_from_secret.items():
            if os.environ.get(env_name):
                continue
            value = payload.get(secret_key, "")
            if value:
                os.environ[env_name] = str(value)
                loaded_export = True
        if loaded_export:
            log.info("Loaded PLATFORM_EXPORT_* from Secrets Manager")

    _loaded = True
