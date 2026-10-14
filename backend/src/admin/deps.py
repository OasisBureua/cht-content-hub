"""Admin API auth — M2M Bearer with CRUD scopes."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from auth.m2m import require_m2m_token
from config import Settings, get_settings

log = logging.getLogger("contenthub.report_packet")


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
    try:
        return require_m2m_token(
            request, settings, resource="reports", authorization=authorization
        )
    except HTTPException as exc:
        request_id = getattr(request.state, "request_id", None) or request.headers.get(
            "X-Request-Id"
        )
        log.warning(
            "report-packet error",
            extra={
                "request_id": request_id,
                "campaign_id": request.path_params.get("campaign_id"),
                "status_code": exc.status_code,
            },
        )
        raise
