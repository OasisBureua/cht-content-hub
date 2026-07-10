"""WordPress webhook ingress — thin ECS route.

Receives HMAC-signed webhooks from the mu-plugin
(`wp-content/mu-plugins/cht-webhook.php`) on Andrew's WordPress site,
verifies the signature, and enqueues the payload to SQS. The Lambda
consumer (deployed separately) drains the queue and writes rows to
`wordpress_events`.

The ECS route deliberately does NOT touch the database — durability
comes from SQS. If the DB is down, the queue still holds the message;
the consumer retries with SQS's built-in redrive to DLQ after 3 attempts.

Response semantics:
- 200: signature valid, payload well-formed, message durably queued to SQS
- 400: malformed JSON or missing required fields
- 401: missing or invalid signature (constant-time HMAC compare)
- 503: SQS SendMessage failed — the event is NOT durably accepted;
       WordPress's mu-plugin fire-and-forgets so it will not retry,
       but this signals the operator via CloudWatch alarms.

Signature scheme mirrors GitHub / Stripe:
- Header: X-CHT-Signature: sha256=<64-hex>
- HMAC-SHA256 of the raw request body using `wordpress_webhook_secret`
- Constant-time compare via hmac.compare_digest
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Annotated, Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from config import Settings, get_settings

logger = logging.getLogger("contenthub.wordpress")

router = APIRouter(prefix="/api/wordpress", tags=["wordpress-ingest"])


# Payload fields the mu-plugin always sends (see cht-webhook.php).
_REQUIRED_FIELDS = frozenset(
    {
        "event",
        "post_id",
        "post_type",
        "slug",
        "title",
        "status",
        "modified_gmt",
        "permalink",
        "categories",
        "tags",
        "site_url",
    }
)

_VALID_EVENTS = frozenset({"published", "updated", "deleted"})


def _valid_signature(
    raw_body: bytes, signature_header: str | None, secret: str
) -> bool:
    """Constant-time HMAC-SHA256 verification. Rejects malformed headers early."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    if not secret:
        # Secret unset in local dev — refuse rather than allow-all, so tests
        # against unconfigured environments fail loudly.
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature_header, expected)


def _shape_check(payload: dict[str, Any]) -> str | None:
    """Return None if payload has required fields with plausible types, else an error string."""
    missing = _REQUIRED_FIELDS - payload.keys()
    if missing:
        return f"missing required fields: {sorted(missing)}"
    if payload["event"] not in _VALID_EVENTS:
        return f"invalid event: {payload['event']!r}"
    if not isinstance(payload["post_id"], int):
        return "post_id must be an integer"
    if not isinstance(payload["categories"], list):
        return "categories must be an array"
    if not isinstance(payload["tags"], list):
        return "tags must be an array"
    return None


def _get_sqs_client(region: str) -> Any:
    """Lazy SQS client — one per process, cached in a closure by boto3."""
    return boto3.client("sqs", region_name=region)


@router.post(
    "/webhook",
    include_in_schema=True,
    summary="Ingress for WordPress publish/update/delete events",
)
async def wordpress_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_cht_signature: Annotated[str | None, Header(alias="X-CHT-Signature")] = None,
    x_cht_event: Annotated[str | None, Header(alias="X-CHT-Event")] = None,
) -> JSONResponse:
    raw_body = await request.body()

    # 1. Signature verification — constant-time compare.
    if not _valid_signature(
        raw_body, x_cht_signature, settings.wordpress_webhook_secret
    ):
        logger.warning(
            "wordpress webhook signature invalid",
            extra={"event_header": x_cht_event, "body_bytes": len(raw_body)},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    # 2. Parse JSON.
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("wordpress webhook malformed json: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON")

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must be a JSON object",
        )

    # 3. Shape check — required fields + type sanity.
    err = _shape_check(payload)
    if err is not None:
        logger.warning("wordpress webhook payload rejected: %s", err)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

    # 4. Enqueue to SQS. Skip in local dev when queue URL is unset — the
    #    signature has been verified, that's the interesting part for tests.
    queue_url = settings.wordpress_events_queue_url
    if not queue_url:
        logger.info(
            "wordpress webhook accepted (dev mode — no queue configured)",
            extra={
                "post_id": payload["post_id"],
                "event": payload["event"],
                "modified_gmt": payload["modified_gmt"],
            },
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"accepted": True, "enqueued": False, "reason": "no queue configured"},
        )

    try:
        sqs = _get_sqs_client(settings.aws_region)
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(payload),
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "wordpress webhook SQS enqueue failed",
            extra={
                "post_id": payload["post_id"],
                "event": payload["event"],
                "error": str(exc),
            },
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"accepted": False, "reason": "queue unavailable"},
        )

    logger.info(
        "wordpress webhook enqueued",
        extra={
            "post_id": payload["post_id"],
            "event": payload["event"],
            "modified_gmt": payload["modified_gmt"],
        },
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"accepted": True, "enqueued": True},
    )
