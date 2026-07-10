"""WordPress event model — raw ingest from Andrew's WordPress site.

Every publish / update / delete event fired by the mu-plugin
(`wp-content/mu-plugins/cht-webhook.php`) lands here as a row. The
ECS webhook route validates the HMAC signature and enqueues to SQS;
the Lambda consumer reads from SQS and inserts here.

Downstream (out of scope for this POC): Content ID parsing, disease-state
categorization fan-out, playlist tag reconciliation, catalog cache clear.

Idempotency is enforced at the DB layer via `UNIQUE (post_id, modified_gmt)`,
mirroring the mu-plugin's dedup key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class WordPressEvent(Base):
    """Raw WordPress webhook event — publish, update, or delete."""

    __tablename__ = "wordpress_events"
    __table_args__ = (
        UniqueConstraint(
            "post_id", "modified_gmt", name="uix_wordpress_events_post_modified"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # WordPress `post.ID` — canonical identifier from the source site.
    post_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # WordPress `post_modified_gmt` — dedup partner with post_id.
    modified_gmt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # `published` | `updated` | `deleted` — matches the X-CHT-Event header.
    event: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # WordPress post type. Usually `post` on Andrew's current site.
    post_type: Mapped[str] = mapped_column(String(64), nullable=False)

    slug: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    permalink: Mapped[str] = mapped_column(String(1000), nullable=False)

    # Category + tag slugs (open-vocabulary — new slugs appear as Andrew adds
    # therapeutic areas). JSONB arrays, not fixed enums, so new slugs flow
    # through without schema changes. See project_contenthub_as_source_of_truth.
    categories: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    site_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # ACF (Advanced Custom Fields) block. `null` on Andrew's current site
    # (he uses native taxonomies, not ACF). Kept forward-compatible.
    acf: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Full request body for replay + debug. Includes headers-free JSON.
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Always true for rows that reach this table — invalid signatures are
    # rejected at the ECS route before enqueueing to SQS. Column exists for
    # future flexibility (e.g., if we ever store unverified events for audit).
    signature_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    # Server-side receive timestamp — when the Lambda consumer inserted the row.
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
