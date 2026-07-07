"""Report templates and non-HubSpot platform integrations."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.campaign import IntegrationSetting, ReportTemplate
from schemas.campaigns import (
    IntegrationPatchIn,
    IntegrationsOut,
    Platform,
    TemplateCreate,
    TemplateOut,
)

_PLATFORM_NOTES = {
    Platform.LINKEDIN: "Configure LinkedIn Campaign Manager API credentials or upload CSV.",
    Platform.META: "Configure Meta Marketing API credentials or upload CSV.",
    Platform.YOUTUBE: "Configure YouTube Analytics credentials or upload CSV.",
    Platform.LIVESTREAM: "Configure livestream provider or upload CSV.",
    Platform.SURVEY: "Configure survey export source or upload CSV.",
}


async def list_templates(db: AsyncSession) -> list[TemplateOut]:
    rows = list(
        (await db.execute(select(ReportTemplate).order_by(ReportTemplate.name))).scalars()
    )
    return [TemplateOut.model_validate(r) for r in rows]


async def create_template(db: AsyncSession, payload: TemplateCreate) -> TemplateOut:
    row = ReportTemplate(
        name=payload.name,
        type=payload.type,
        description=payload.description,
    )
    db.add(row)
    await db.flush()
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
            "configured": bool(config.get("enabled") or config.get("stub")),
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
