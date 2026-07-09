"""Platform API connectors for campaign report sync."""

from services.connectors.common import ConnectorError, FetchResult
from services.connectors.linkedin_ads import fetch_linkedin_ads_metrics
from services.connectors.youtube import fetch_youtube_metrics

__all__ = [
    "ConnectorError",
    "FetchResult",
    "fetch_linkedin_ads_metrics",
    "fetch_youtube_metrics",
]
