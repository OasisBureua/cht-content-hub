"""KOL (Key Opinion Leader) models - doctors and their groupings."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.project import Project
    from models.shoot import Shoot


class KOL(Base):
    """
    Key Opinion Leader - an individual doctor/expert.

    Represents doctors like Dr. Jason Mouabbi, Dr. Virginia Kaklamani, etc.
    KOLs can belong to multiple KOL groups across different projects.
    """

    __tablename__ = "kols"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g., "MD", "PhD"
    specialty: Mapped[str | None] = mapped_column(String(255), nullable=True)  # e.g., "Medical Oncology"
    institution: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # /kol-network grouping. Consumed by GET /api/public/kols and the CHT
    # /kol-network public page. Canonical taxonomy in services/kol_regions.py.
    region: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    region_label: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # HCP Intel bridge — links this KOL to a row in hcps.npi. Resolved by
    # hcp_intel.kol_hcp_matcher. See BACKLOG.md P3b for context.
    hcp_npi: Mapped[str | None] = mapped_column(
        String(10), ForeignKey("hcps.npi", ondelete="SET NULL"), nullable=True
    )
    hcp_match_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unresolved", server_default="unresolved"
    )  # 'unresolved' | 'auto_locked' | 'needs_review' | 'manually_locked' | 'no_match'
    hcp_match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    hcp_candidates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    hcp_resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relationships
    group_memberships: Mapped[list["KOLGroupMember"]] = relationship(
        "KOLGroupMember",
        back_populates="kol",
        cascade="all, delete-orphan"
    )

    @property
    def groups(self) -> list["KOLGroup"]:
        """Get all KOL groups this doctor belongs to."""
        return [m.kol_group for m in self.group_memberships]

    def __repr__(self) -> str:
        return f"<KOL {self.name}>"


class KOLGroup(Base):
    """
    A group of KOLs that appear together in podcast sessions.

    Examples: "Mouabbi/O'Shaughnessy/Rimawi", "Kang/Bardia"
    These represent the recurring doctor pairings from the spreadsheet.
    """

    __tablename__ = "kol_groups"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)  # e.g., "Mouabbi/O'Shaughnessy/Rimawi"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # From spreadsheet
    video_count: Mapped[int | None] = mapped_column(nullable=True)  # "# of Videos" column
    publish_day: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "Day" column: Monday, Tuesday, etc.

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="kol_groups")
    members: Mapped[list["KOLGroupMember"]] = relationship(
        "KOLGroupMember",
        back_populates="kol_group",
        cascade="all, delete-orphan"
    )
    shoots: Mapped[list["Shoot"]] = relationship(
        "Shoot",
        back_populates="kol_group",
        foreign_keys="Shoot.kol_group_id"
    )

    @property
    def kols(self) -> list[KOL]:
        """Get all KOLs in this group."""
        return [m.kol for m in self.members]

    def __repr__(self) -> str:
        return f"<KOLGroup {self.name}>"


class KOLGroupMember(Base):
    """Association table linking KOLs to KOL groups."""

    __tablename__ = "kol_group_members"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4())
    )
    kol_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("kols.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    kol_group_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("kol_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Role within the group (optional)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g., "host", "guest"

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Relationships
    kol: Mapped[KOL] = relationship("KOL", back_populates="group_memberships")
    kol_group: Mapped[KOLGroup] = relationship("KOLGroup", back_populates="members")

    def __repr__(self) -> str:
        return f"<KOLGroupMember {self.kol_id} in {self.kol_group_id}>"
