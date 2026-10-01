"""Report templates and non-HubSpot platform integrations."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.campaign import IntegrationSetting, ReportTemplate
from schemas.campaigns import (
    IntegrationPatchIn,
    IntegrationsOut,
    Platform,
    TemplateCreate,
    TemplateOut,
)

_PLATFORM_NOTES = {
    Platform.LINKEDIN: (
        "LinkedIn Ads: set accessToken + adAccountId (or env vars) and "
        "campaignMap.linkedinCampaignIds per Hub campaign."
    ),
    Platform.META: "Configure Meta Marketing API credentials or upload CSV.",
    Platform.YOUTUBE: (
        "YouTube Data API: set apiKey + channelId/channelHandle (or env vars). "
        "Optional campaignMap.youtubeVideoIds to scope videos."
    ),
    Platform.LIVESTREAM: "Configure livestream provider or upload CSV.",
    Platform.SURVEY: "Configure survey export source or upload CSV.",
}


def _env_credentials_ready(platform: Platform) -> bool:
    settings = get_settings()
    if platform == Platform.LINKEDIN:
        return bool(settings.linkedin_ads_access_token and settings.linkedin_ad_account_id)
    if platform == Platform.YOUTUBE:
        return bool(
            settings.youtube_api_key
            and (settings.youtube_channel_id or settings.youtube_channel_handle)
        )
    return False


async def list_templates(db: AsyncSession) -> list[TemplateOut]:
    rows = list(
        (await db.execute(select(ReportTemplate).order_by(ReportTemplate.name))).scalars()
    )
    return [TemplateOut.model_validate(r) for r in rows]


async def create_template(db: AsyncSession, payload: TemplateCreate) -> TemplateOut:
    if payload.s3_key and not payload.semver:
        raise HTTPException(status_code=422, detail="semver is required when s3_key is set")
    row = ReportTemplate(
        name=payload.name,
        type=payload.type,
        description=payload.description,
        semver=payload.semver,
        s3_key=payload.s3_key,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        # get_db rolls the session back when the exception propagates.
        raise HTTPException(
            status_code=409,
            detail=f"Template {payload.type} {payload.semver} already exists",
        ) from exc
    await db.refresh(row)
    return TemplateOut.model_validate(row)


async def delete_template(db: AsyncSession, template_id: int) -> None:
    row = await db.get(ReportTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(row)
    await db.flush()


async def get_integrations(db: AsyncSession) -> IntegrationsOut:
    rows = {
        row.key: row.value_json
        for row in (await db.execute(select(IntegrationSetting))).scalars()
    }
    platforms: dict[str, dict] = {}
    for platform in Platform:
        config = rows.get(platform.value, {})
        platforms[platform.value] = {
            "configured": bool(
                config.get("enabled") or config.get("stub") or _env_credentials_ready(platform)
            ),
            "enabled": bool(config.get("enabled")),
            "note": _PLATFORM_NOTES[platform],
            "lastTestedAt": config.get("lastTestedAt"),
        }
    return IntegrationsOut(platforms=platforms)


async def patch_integrations(
    db: AsyncSession, payload: IntegrationPatchIn
) -> IntegrationsOut:
    now = datetime.now(timezone.utc).isoformat()
    for key, value in payload.platforms.items():
        if key not in {p.value for p in Platform}:
            raise HTTPException(status_code=400, detail=f"Unknown platform: {key}")
        existing = await db.get(IntegrationSetting, key)
        merged = {**(existing.value_json if existing else {}), **value}
        merged["updatedAt"] = now
        if existing:
            existing.value_json = merged
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(IntegrationSetting(key=key, value_json=merged))
    await db.flush()
    return await get_integrations(db)
