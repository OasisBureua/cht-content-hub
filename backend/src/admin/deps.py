"""Admin API auth — M2M Bearer with CRUD scopes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from auth.m2m import require_m2m_token
from config import Settings, get_settings


def verify_admin_api_key(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Guard /api/admin/* — Bearer ``hub/admin.{crud}`` required."""
    return require_m2m_token(
        request, settings, resource="admin", authorization=authorization
    )


def verify_reports_access(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Guard report-packet — Bearer ``hub/reports.{crud}`` required."""
    return require_m2m_token(
        request, settings, resource="reports", authorization=authorization
    )
