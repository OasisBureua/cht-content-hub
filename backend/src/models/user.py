"""Minimal users table — satisfies HCP Intel FKs until admin auth (Step 4+)."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class User(Base):
    """Placeholder for FK targets (feed_subscriptions, unmatched_attendees, hcp_ai_briefs)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)

    def __repr__(self) -> str:
        return f"<User {self.id}>"
