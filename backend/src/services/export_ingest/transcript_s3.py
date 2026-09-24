"""Fetch raw WebVTT objects for CPR-13 transcript ingest.

``S3TranscriptStore`` wraps boto3 ``get_object``. Tests use
``MemoryTranscriptStore`` (or a mock client) — no live AWS required.
"""

from __future__ import annotations

from typing import Protocol

import boto3


class TranscriptStore(Protocol):
    def get_vtt(self, key: str) -> str:
        """Return UTF-8 WebVTT body for an object key."""
        ...


class TranscriptStoreError(RuntimeError):
    """Raised when a transcript object cannot be read."""


class MemoryTranscriptStore:
    """In-memory key → VTT body map for fixtures / unit tests."""

    def __init__(self, objects: dict[str, str] | None = None) -> None:
        self._objects = dict(objects or {})

    def put(self, key: str, body: str) -> None:
        self._objects[key] = body

    def get_vtt(self, key: str) -> str:
        try:
            return self._objects[key]
        except KeyError as exc:
            raise TranscriptStoreError(f"Transcript key not found: {key}") from exc


class S3TranscriptStore:
    """Read transcript objects from an S3 bucket via GetObject."""

    def __init__(
        self,
        bucket: str,
        *,
        client=None,
        region_name: str | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("S3 transcript bucket is required")
        self.bucket = bucket
        self._client = client or boto3.client("s3", region_name=region_name)

    def get_vtt(self, key: str) -> str:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"].read()
        except Exception as exc:  # noqa: BLE001 — normalize boto/client errors
            raise TranscriptStoreError(
                f"Failed to get s3://{self.bucket}/{key}: {exc}"
            ) from exc
        if isinstance(body, bytes):
            return body.decode("utf-8")
        return str(body)
