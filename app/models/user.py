"""ORM model for a registered application user.

Distinct from the single hard-coded admin (which is password-only, no row): these are
self-service accounts that own webhooks. A user authenticates an HTTP request (and a
live WS session) with a JWT minted in ``app/core/security.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.webhook import Webhook


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    # argon2id hash; the salt and parameters are encoded inside the string itself.
    password_hash: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    # NULL until the first successful login.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    webhooks: Mapped[list[Webhook]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
