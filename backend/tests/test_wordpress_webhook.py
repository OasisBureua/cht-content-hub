"""Tests for POST /api/wordpress/webhook.

Covers signature verification, shape checks, response codes, and SQS
enqueue behavior. No real AWS — SQS is monkeypatched to a fake client.

Signature scheme mirrors GitHub / Stripe: `X-CHT-Signature: sha256=<hex>`
where hex = HMAC-SHA256(raw_body, secret).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from config import get_settings

# The shared secret used across these tests — mirrors what would be set
# via WORDPRESS_WEBHOOK_SECRET env var in dev/prod (already provisioned
# in `contenthub-dev-app-secrets` as key `wordpress_webhook_secret`).
_TEST_SECRET = "test-webhook-secret-abcdef1234567890" * 2  # 64 chars-ish


def _sign(body: bytes, secret: str = _TEST_SECRET) -> str:
    """Compute the X-CHT-Signature header value for a given body."""
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def _valid_payload() -> dict:
    """A well-formed publish event matching the mu-plugin's shape."""
    return {
        "event": "published",
        "post_id": 12345,
        "post_type": "post",
        "slug": "her2-treatment-updates-2026",
        "title": "HER2 Treatment Updates 2026",
        "status": "publish",
        "modified_gmt": "2026-07-09 21:00:00",
        "permalink": "https://communityhealth.media/her2-treatment-updates-2026/",
        "categories": ["her2", "high-risk-disease"],
        "tags": ["kol-video"],
        "site_url": "https://communityhealth.media",
        "acf": None,
    }


@pytest.fixture(autouse=True)
def _set_webhook_secret(monkeypatch):
    """Point every test at the known test secret + empty queue URL."""
    monkeypatch.setenv("WORDPRESS_WEBHOOK_SECRET", _TEST_SECRET)
    monkeypatch.setenv("WORDPRESS_EVENTS_QUEUE_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────────────
# Signature verification
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_signature_header_returns_401(http_client: AsyncClient):
    body = json.dumps(_valid_payload()).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_malformed_signature_prefix_returns_401(http_client: AsyncClient):
    body = json.dumps(_valid_payload()).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-CHT-Signature": "md5=deadbeef",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_signature_returns_401(http_client: AsyncClient):
    body = json.dumps(_valid_payload()).encode("utf-8")
    # Sign with a different secret — same shape, wrong key.
    wrong_sig = _sign(body, secret="not-the-real-secret" * 3)
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": wrong_sig},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tampered_body_fails_signature(http_client: AsyncClient):
    """Signing one body then sending a different body must fail."""
    original = json.dumps(_valid_payload()).encode("utf-8")
    signature = _sign(original)

    tampered_payload = _valid_payload()
    tampered_payload["title"] = "MALICIOUS EDIT"
    tampered_body = json.dumps(tampered_payload).encode("utf-8")

    response = await http_client.post(
        "/api/wordpress/webhook",
        content=tampered_body,  # sent body != signed body
        headers={"Content-Type": "application/json", "X-CHT-Signature": signature},
    )
    assert response.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Payload shape checks
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_json_returns_400(http_client: AsyncClient):
    body = b"{not json"
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_non_object_payload_returns_400(http_client: AsyncClient):
    body = json.dumps(["not", "an", "object"]).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_missing_required_fields_returns_400(http_client: AsyncClient):
    payload = _valid_payload()
    del payload["post_id"]
    del payload["categories"]
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400
    detail = response.json().get("error", {}).get("message") or response.json().get(
        "detail"
    )
    assert "post_id" in str(detail) and "categories" in str(detail)


@pytest.mark.asyncio
async def test_invalid_event_returns_400(http_client: AsyncClient):
    payload = _valid_payload()
    payload["event"] = "not-a-real-event"
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_wrong_type_categories_returns_400(http_client: AsyncClient):
    payload = _valid_payload()
    payload["categories"] = "not-an-array"  # should be list
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_series_field_optional_when_absent(http_client: AsyncClient):
    """Pre-v0.5 mu-plugin payloads omit `series` entirely — must still 200.
    Backwards-tolerance is the whole point of `series` being optional in
    the shape-check contract."""
    payload = _valid_payload()
    assert "series" not in payload  # baseline: fixture doesn't set it
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_series_valid_array_accepted(http_client: AsyncClient):
    """v0.5 mu-plugin sends `series` as a slug array."""
    payload = _valid_payload()
    payload["series"] = ["dr-iyengar-dr-hurvitz", "her2-deep-dive"]
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_series_empty_array_accepted(http_client: AsyncClient):
    """A post assigned to no series terms sends `series: []` — legal."""
    payload = _valid_payload()
    payload["series"] = []
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_series_non_array_returns_400(http_client: AsyncClient):
    payload = _valid_payload()
    payload["series"] = "not-an-array"
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_series_non_string_entries_return_400(http_client: AsyncClient):
    """Type-confusion guard — series entries must all be strings."""
    payload = _valid_payload()
    payload["series"] = ["valid-slug", 42, {"nested": "object"}]
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Happy path — dev mode (no queue configured)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_signature_no_queue_returns_200_not_enqueued(
    http_client: AsyncClient,
):
    body = json.dumps(_valid_payload()).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-CHT-Signature": _sign(body),
            "X-CHT-Event": "published",
        },
    )
    assert response.status_code == 200
    body_json = response.json()
    assert body_json["accepted"] is True
    assert body_json["enqueued"] is False


@pytest.mark.asyncio
async def test_valid_publish_update_delete_all_accepted(http_client: AsyncClient):
    """The three canonical event types all pass signature + shape checks."""
    for event in ["published", "updated", "deleted"]:
        payload = _valid_payload()
        payload["event"] = event
        body = json.dumps(payload).encode("utf-8")
        response = await http_client.post(
            "/api/wordpress/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-CHT-Signature": _sign(body),
                "X-CHT-Event": event,
            },
        )
        assert response.status_code == 200, f"event={event} failed"


# ─────────────────────────────────────────────────────────────────────────────
# Happy path — with SQS enqueue (monkeypatched)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_success_returns_200_and_calls_sqs(
    http_client: AsyncClient, monkeypatch
):
    monkeypatch.setenv(
        "WORDPRESS_EVENTS_QUEUE_URL",
        "https://sqs.us-east-1.amazonaws.com/000000000000/test-queue",
    )
    get_settings.cache_clear()

    fake_sqs = MagicMock()
    fake_sqs.send_message.return_value = {"MessageId": "abc-123"}
    import wordpress.router as wp_router

    monkeypatch.setattr(wp_router, "_get_sqs_client", lambda region: fake_sqs)

    body = json.dumps(_valid_payload()).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "enqueued": True}

    fake_sqs.send_message.assert_called_once()
    kwargs = fake_sqs.send_message.call_args.kwargs
    assert kwargs["QueueUrl"].endswith("test-queue")
    # MessageBody is the payload we sent, round-tripped through json.
    assert json.loads(kwargs["MessageBody"])["post_id"] == 12345


@pytest.mark.asyncio
async def test_sqs_failure_returns_503(http_client: AsyncClient, monkeypatch):
    from botocore.exceptions import ClientError

    monkeypatch.setenv(
        "WORDPRESS_EVENTS_QUEUE_URL",
        "https://sqs.us-east-1.amazonaws.com/000000000000/test-queue",
    )
    get_settings.cache_clear()

    fake_sqs = MagicMock()
    fake_sqs.send_message.side_effect = ClientError(
        {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue"}},
        "SendMessage",
    )
    import wordpress.router as wp_router

    monkeypatch.setattr(wp_router, "_get_sqs_client", lambda region: fake_sqs)

    body = json.dumps(_valid_payload()).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 503
    assert response.json()["accepted"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Secret-not-configured edge case
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_term_updated_valid_payload_accepted(http_client: AsyncClient):
    """v0.6 mu-plugin sends term_updated events on taxonomy edits."""
    payload = {
        "event": "term_updated",
        "taxonomy": "series",
        "term_id": 42,
        "slug": "dr-iyengar-dr-hurvitz",
        "name": "Drs. Iyengar & Hurvitz",
        "description": "A doctor-pair series",
        "parent_slug": None,
    }
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_term_deleted_valid_payload_accepted(http_client: AsyncClient):
    """term_deleted event carries the minimum identifying fields."""
    payload = {
        "event": "term_deleted",
        "taxonomy": "series",
        "term_id": 42,
        "slug": "retired-series",
    }
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_term_event_all_valid_taxonomies_accepted(http_client: AsyncClient):
    """series, category, and post_tag are all valid taxonomy identifiers."""
    for taxonomy in ["series", "category", "post_tag"]:
        payload = {
            "event": "term_updated",
            "taxonomy": taxonomy,
            "term_id": 7,
            "slug": f"{taxonomy}-example",
            "name": f"{taxonomy} example",
        }
        body = json.dumps(payload).encode("utf-8")
        response = await http_client.post(
            "/api/wordpress/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
        )
        assert response.status_code == 200, f"taxonomy={taxonomy} failed"


@pytest.mark.asyncio
async def test_term_event_invalid_taxonomy_returns_400(http_client: AsyncClient):
    payload = {
        "event": "term_updated",
        "taxonomy": "not-a-real-taxonomy",
        "term_id": 42,
        "slug": "whatever",
    }
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_term_event_missing_required_field_returns_400(http_client: AsyncClient):
    payload = {
        "event": "term_updated",
        "taxonomy": "series",
        # missing term_id + slug
    }
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_term_event_empty_slug_returns_400(http_client: AsyncClient):
    payload = {
        "event": "term_updated",
        "taxonomy": "series",
        "term_id": 42,
        "slug": "",  # empty is rejected — slug is identity
    }
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_term_event_non_integer_term_id_returns_400(http_client: AsyncClient):
    payload = {
        "event": "term_updated",
        "taxonomy": "series",
        "term_id": "not-a-number",
        "slug": "test",
    }
    body = json.dumps(payload).encode("utf-8")
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": _sign(body)},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_term_event_still_signature_verified(http_client: AsyncClient):
    """Term events go through the same HMAC path as post events."""
    payload = {
        "event": "term_updated",
        "taxonomy": "series",
        "term_id": 42,
        "slug": "test",
        "name": "Test",
    }
    body = json.dumps(payload).encode("utf-8")
    # No signature → 401 even for a well-formed term event
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_empty_secret_rejects_even_matching_signature(
    http_client: AsyncClient, monkeypatch
):
    """When WORDPRESS_WEBHOOK_SECRET is unset, all requests must fail
    signature check — never allow-all silently."""
    monkeypatch.setenv("WORDPRESS_WEBHOOK_SECRET", "")
    get_settings.cache_clear()

    body = json.dumps(_valid_payload()).encode("utf-8")
    # Signature computed against the empty string — even a "matching" hash
    # should fail because the route explicitly refuses when secret is unset.
    sig = "sha256=" + hmac.new(b"", body, hashlib.sha256).hexdigest()
    response = await http_client.post(
        "/api/wordpress/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-CHT-Signature": sig},
    )
    assert response.status_code == 401
