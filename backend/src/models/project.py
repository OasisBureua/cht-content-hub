"""Project model - represents a drug/treatment program for a client."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.client import Client
    from models.kol import KOLGroup
    from models.shoot import Shoot


class Project(Base):
    """
    Project within a client - typically a drug or treatment program.

    Examples: Enhertu, Lymparza, DB09, TB02, Neratinib
    Each project maps to a sheet in the Release Schedules spreadsheet.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4())
    )
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "DB09", "EBC"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

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
    client: Mapped["Client"] = relationship("Client", back_populates="projects")
    kol_groups: Mapped[list["KOLGroup"]] = relationship(
        "KOLGroup",
        back_populates="project",
        cascade="all, delete-orphan"
    )
    shoots: Mapped[list["Shoot"]] = relationship(
        "Shoot",
        back_populates="project",
        foreign_keys="Shoot.project_id"
    )

    def __repr__(self) -> str:
        return f"<Project {self.code}: {self.name}>"
