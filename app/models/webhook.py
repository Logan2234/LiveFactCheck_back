"""ORM model for a user-registered alert webhook.

A webhook belongs to a :class:`~app.models.user.User`. When a claim whose status is in
``trigger_statuses`` is verified in that user's own live session, the server POSTs the
claim to ``url`` (best-effort), signing the body with ``secret`` (HMAC-SHA256). The
``secret`` is stored in clear because it's needed to *sign* the outgoing request — it is
a shared secret with the receiver, not a credential to verify like a password.

``last_triggered_at`` / ``last_error`` / ``failure_count`` record delivery health.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    # Destination type (WebhookKind value) chosen by the user; drives the payload shape.
    kind: Mapped[str] = mapped_column(String, default="custom")
    # Shared secret used to sign the outgoing POST (HMAC). Stored in clear on purpose.
    secret: Mapped[str] = mapped_column(String)
    # Claim statuses that fire this webhook (VerificationStatus values).
    trigger_statuses: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    # Delivery health, updated after each attempt.
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship(back_populates="webhooks")
