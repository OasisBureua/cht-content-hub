"""Which LinkedIn Ads access token to use (CPR-15).

With a refresh token and the app credentials, every run gets a fresh access
token, so the 60-day access-token expiry stops mattering. Without them, the
static access token is used and must be replaced by hand before it expires.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from config import Settings
from services.connectors.common import ConnectorError, integration_or_env
from services.connectors.linkedin_ads import LinkedInAccessToken, refresh_linkedin_access_token

# Refreshed tokens are reused while they have this much life left.
_REUSE_MARGIN = timedelta(minutes=10)
# A failed refresh is not retried for this long, so one job run doesn't retry
# per campaign; the API process tries again later.
_FAILED_RETRY_AFTER = timedelta(minutes=15)
_refreshed: dict[str, LinkedInAccessToken] = {}
_failed: dict[str, tuple[datetime, ConnectorError]] = {}


async def linkedin_ads_access_token(
    settings: Settings, integration: dict[str, Any]
) -> tuple[str, LinkedInAccessToken | None]:
    """The access token for adAnalytics, plus the refresh result when one was used."""
    refresh_token = settings.linkedin_ads_refresh_token.strip()
    if refresh_token and settings.linkedin_ads_client_id and settings.linkedin_ads_client_secret:
        key = hashlib.sha256(refresh_token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        cached = _refreshed.get(key)
        if cached and cached.expires_at - now > _REUSE_MARGIN:
            return cached.access_token, cached
        failed = _failed.get(key)
        if failed and now - failed[0] < _FAILED_RETRY_AFTER:
            raise failed[1]
        try:
            fresh = await refresh_linkedin_access_token(
                refresh_token=refresh_token,
                client_id=settings.linkedin_ads_client_id,
                client_secret=settings.linkedin_ads_client_secret,
            )
        except ConnectorError as exc:
            _failed[key] = (now, exc)
            raise
        _failed.pop(key, None)
        _refreshed[key] = fresh
        return fresh.access_token, fresh

    static = integration_or_env(
        integration,
        integration_key="accessToken",
        env_value=settings.linkedin_ads_access_token,
    )
    return static, None
