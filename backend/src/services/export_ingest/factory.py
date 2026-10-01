"""Build an ``ExportClient`` from Settings (live HTTP when configured)."""

from __future__ import annotations

from config import Settings
from services.export_ingest.client import ExportClient, ExportClientError
from services.export_ingest.client_http import ExportHttpMode, HttpExportClient


def build_http_export_client(settings: Settings) -> HttpExportClient:
    """Construct the live HTTP client. Raises if base URL is unset."""
    if not settings.platform_export_base_url:
        raise ExportClientError(
            "PLATFORM_EXPORT_BASE_URL is not configured — "
            "use FixtureExportClient until CPR-12 is available"
        )
    return HttpExportClient(
        settings.platform_export_base_url,
        mode=ExportHttpMode(settings.platform_export_http_mode),
        token_url=settings.platform_export_token_url,
        client_id=settings.platform_export_client_id,
        client_secret=settings.platform_export_client_secret,
        export_scope=settings.platform_export_scope,
    )


def try_build_http_export_client(settings: Settings) -> ExportClient | None:
    """Return HTTP client when base URL is set; otherwise ``None``."""
    if not settings.platform_export_base_url:
        return None
    return build_http_export_client(settings)
