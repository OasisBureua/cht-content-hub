"""Admin API routes — campaigns, platform sync, reports (CHT proxy target).

Content Hub owns non-HubSpot platform data (snapshots, sync, connectors).
CHT orchestrates reports: GET campaign + platform-data from Hub, then
POST .../report/generate. HubSpot sync stays on CHT → PATCH campaign.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from admin.cache import notify_cht_cache_clear
from admin.deps import verify_admin_api_key
from database import get_db
from schemas.campaigns import (
    AnalyticsReportOut,
    CampaignCreate,
    CampaignListOut,
    CampaignOut,
    CampaignUpdate,
    CsvUploadCreate,
    CsvUploadListOut,
    CsvUploadOut,
    DataValidationOut,
    ExecutiveReportOut,
    InsightsOut,
    IntegrationPatchIn,
    IntegrationsOut,
    Platform,
    PlatformDataListOut,
    PlatformSyncAllOut,
    PlatformSyncResultOut,
    TemplateCreate,
    TemplateListOut,
    TemplateOut,
)
from services import campaign_integrations, campaign_reports, campaigns, platform_data

router = APIRouter(prefix="/api/admin", tags=["admin-campaigns"])


@router.get("/campaigns", response_model=CampaignListOut)
async def list_campaigns(
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = Query(default=None),
) -> CampaignListOut:
    items, total = await campaigns.list_campaigns(db, q=q)
    return CampaignListOut(items=items, total=total)


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CampaignOut:
    return await campaigns.get_campaign(db, campaign_id)


@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CampaignOut:
    out = await campaigns.create_campaign(db, payload)
    await notify_cht_cache_clear(scope="contenthub")
    return out


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CampaignOut:
    out = await campaigns.update_campaign(db, campaign_id, payload)
    await notify_cht_cache_clear(scope="contenthub")
    return out


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await campaigns.delete_campaign(db, campaign_id)
    await notify_cht_cache_clear(scope="contenthub")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/campaigns/{campaign_id}/platform-data", response_model=PlatformDataListOut)
async def get_campaign_platform_data(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlatformDataListOut:
    return await platform_data.list_platform_data(db, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/platforms/{platform}/sync",
    response_model=PlatformSyncResultOut,
)
async def sync_campaign_platform(
    campaign_id: int,
    platform: Platform,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlatformSyncResultOut:
    result = await platform_data.sync_platform(
        db, campaign_id, platform.value, trigger="manual"
    )
    await notify_cht_cache_clear(scope="contenthub")
    return result


@router.post(
    "/campaigns/{campaign_id}/sync-all",
    response_model=PlatformSyncAllOut,
)
async def sync_campaign_all_platforms(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlatformSyncAllOut:
    items = await platform_data.sync_all_platforms(db, campaign_id)
    await notify_cht_cache_clear(scope="contenthub")
    return PlatformSyncAllOut(items=items)


@router.get("/campaigns/{campaign_id}/uploads", response_model=CsvUploadListOut)
async def list_campaign_uploads(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CsvUploadListOut:
    items = await campaigns.list_uploads(db, campaign_id)
    return CsvUploadListOut(items=items)


@router.post(
    "/campaigns/{campaign_id}/uploads",
    response_model=CsvUploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_campaign_csv(
    campaign_id: int,
    payload: CsvUploadCreate,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CsvUploadOut:
    out = await campaigns.upload_csv(db, campaign_id, payload)
    await notify_cht_cache_clear(scope="contenthub")
    return out


@router.get("/campaigns/{campaign_id}/validation", response_model=DataValidationOut)
async def get_campaign_validation(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DataValidationOut:
    return await campaign_reports.build_data_validation(db, campaign_id)


@router.post("/campaigns/{campaign_id}/insights", response_model=InsightsOut)
async def generate_campaign_insights(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InsightsOut:
    out = await campaign_reports.generate_ai_insights(db, campaign_id)
    await notify_cht_cache_clear(scope="contenthub")
    return out


@router.post(
    "/campaigns/{campaign_id}/report/generate",
    response_model=AnalyticsReportOut,
)
async def generate_analytics_report(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnalyticsReportOut:
    """CHT server-to-server — builds from stored snapshots + hubspot_raw_data."""
    return await campaign_reports.build_analytics_report(db, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/executive-report/generate",
    response_model=ExecutiveReportOut,
)
async def generate_executive_report(
    campaign_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExecutiveReportOut:
    return await campaign_reports.build_executive_report(db, campaign_id)


@router.get("/integrations", response_model=IntegrationsOut)
async def get_integrations(
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntegrationsOut:
    return await campaign_integrations.get_integrations(db)


@router.patch("/integrations", response_model=IntegrationsOut)
async def patch_integrations(
    payload: IntegrationPatchIn,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntegrationsOut:
    out = await campaign_integrations.patch_integrations(db, payload)
    await notify_cht_cache_clear(scope="contenthub")
    return out


@router.get("/templates", response_model=TemplateListOut)
async def list_templates(
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TemplateListOut:
    items = await campaign_integrations.list_templates(db)
    return TemplateListOut(items=items)


@router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TemplateOut:
    return await campaign_integrations.create_template(db, payload)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    _key: Annotated[str, Depends(verify_admin_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await campaign_integrations.delete_template(db, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
