"""Shared dependencies for public API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from auth.m2m import require_m2m_token
from config import Settings, get_settings


def verify_public_api_key(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Guard /api/public/* — Bearer ``hub/catalog.{crud}`` required."""
    return require_m2m_token(
        request, settings, resource="catalog", authorization=authorization
    )
