"""ORM model for a persisted WebSocket session.

A session row is the parent of its transcript segments and verified claims. It
holds only its identity plus ``chunks_received`` (a raw audio-frame counter that
isn't derivable from anything else and is written once at close). Everything else
— token totals, latencies, claim ratios — is derived at read time by
``app.services.stats`` from the child rows, never denormalised here.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.claim import Claim
    from app.models.transcript_segment import TranscriptSegment


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    # NULL until the connection closes; an open session has no end yet.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    client_host: Mapped[str] = mapped_column(String)
    # Raw count of received audio frames — operational, not derivable (we don't
    # store the audio). Written once at session close from the in-memory counter.
    chunks_received: Mapped[int] = mapped_column(Integer, default=0)

    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.seq",
    )
    claims: Mapped[list[Claim]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
