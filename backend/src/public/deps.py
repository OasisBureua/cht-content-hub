"""Shared dependencies for public API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from config import Settings, get_settings


def verify_public_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    if x_api_key != settings.public_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
