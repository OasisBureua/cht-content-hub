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
    if app_arn and not os.environ.get("INTERNAL_CACHE_SECRET"):
        payload = json.loads(client.get_secret_value(SecretId=app_arn)["SecretString"])
        secret = payload.get("internal_cache_secret", "")
        if secret:
            os.environ["INTERNAL_CACHE_SECRET"] = secret
            log.info("Loaded INTERNAL_CACHE_SECRET from Secrets Manager")

    _loaded = True
