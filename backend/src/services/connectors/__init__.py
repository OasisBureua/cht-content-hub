"""Platform API connectors for campaign report sync."""

from services.connectors.common import (
    ConnectorError,
    ConnectorNoData,
    ConnectorNotMapped,
    FetchResult,
)
from services.connectors.linkedin_ads import (
    fetch_linkedin_ads_metrics,
    linkedin_token_expires_at,
)

__all__ = [
    "ConnectorError",
    "ConnectorNoData",
    "ConnectorNotMapped",
    "FetchResult",
    "fetch_linkedin_ads_metrics",
    "linkedin_token_expires_at",
]
