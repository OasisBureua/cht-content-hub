"""ORM models — KOL + HCP Intel (Content Hub producer scope)."""

from database import Base

from models.client import Client
from models.kol import KOL, KOLGroup, KOLGroupMember
from models.project import Project
from models.shoot import Shoot
from models.campaign import Campaign, CampaignPlatformData, ReportTemplate

# HCP Intel — full package for migrations + Step 4+ ingestion
from hcp_intel.models import (  # noqa: F401
    DataSyncState,
    DrugClass,
    DrugToClass,
    FeedItem,
    FeedSource,
    FeedSubscription,
    HCP,
    HCPAIBrief,
    HCPSignal,
    Manufacturer,
    Medication,
    NCIDesignation,
    NIHGrant,
    OpenPaymentsRecord,
    RxDrugAlias,
    RxVolume,
    SignalDrug,
    UnmatchedAttendee,
    WebinarAttendance,
    WebinarDrug,
    WebinarEvent,
    WebinarForm,
)

__all__ = [
    "Base",
    "Client",
    "Project",
    "KOL",
    "KOLGroup",
    "KOLGroupMember",
    "Shoot",
    "User",
    "HCP",
    "HCPSignal",
]
