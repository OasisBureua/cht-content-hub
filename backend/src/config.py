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


@lru_cache
def get_settings() -> Settings:
    return Settings()
