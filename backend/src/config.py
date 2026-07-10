"""Application settings for contenthub-api."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Content Hub API"
    debug: bool = False
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    app_version: str = Field(default="local", validation_alias="APP_VERSION")
    aws_region: str = Field(default="us-east-1", validation_alias="AWS_REGION")
    service_role: str = Field(default="api", validation_alias="CONTENTHUB_SERVICE_ROLE")
    container_image: str = Field(default="", validation_alias="CONTAINER_IMAGE")

    database_url: str = Field(
        default="postgresql+asyncpg://contenthub:contenthub@localhost:5433/contenthub_producer",
        validation_alias="DATABASE_URL",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # CHT server-to-server auth for /api/public/*
    public_api_key: str = "change-this-in-production"
    # CHT proxy auth for /api/admin/* (defaults to public key in dev)
    admin_api_key: str = Field(
        default="",
        validation_alias="ADMIN_API_KEY",
    )

    @property
    def resolved_admin_api_key(self) -> str:
        return self.admin_api_key or self.public_api_key

    # LinkedIn Ads (campaign report sync)
    linkedin_ads_access_token: str = Field(
        default="",
        validation_alias="LINKEDIN_ADS_ACCESS_TOKEN",
    )
    linkedin_ad_account_id: str = Field(
        default="",
        validation_alias="LINKEDIN_AD_ACCOUNT_ID",
    )

    # YouTube (Data API v3 — views per video)
    youtube_api_key: str = Field(default="", validation_alias="YOUTUBE_API_KEY")
    youtube_channel_id: str = Field(default="", validation_alias="YOUTUBE_CHANNEL_ID")
    youtube_channel_handle: str = Field(
        default="",
        validation_alias="YOUTUBE_CHANNEL_HANDLE",
    )

    # WordPress webhook — shared secret with Andrew's wp-config.php, used for
    # HMAC-SHA256 signature validation on POST /api/wordpress/webhook.
    wordpress_webhook_secret: str = Field(
        default="",
        validation_alias="WORDPRESS_WEBHOOK_SECRET",
    )

    # SQS queue receiving validated WordPress webhook payloads. ECS route
    # enqueues here; Lambda consumer drains it. Empty in local dev — the
    # webhook route no-ops the SQS call and returns 200 for testing.
    wordpress_events_queue_url: str = Field(
        default="",
        validation_alias="WORDPRESS_EVENTS_QUEUE_URL",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
