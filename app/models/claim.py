"""ORM model for a persisted, verified claim.

Mirrors the ``ClaimBase`` contract fields (see ``app/schemas/claim.py``) plus the
DB-side links and ``created_at``. Only the *final* state of a claim is stored —
never the transient ``pending`` placeholder shown live over the WebSocket.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.session import Session
    from app.models.transcript_segment import TranscriptSegment


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    # A claim outlives the link to its source utterance: SET NULL, not CASCADE.
    segment_id: Mapped[str | None] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="SET NULL"), default=None
    )

    # Contract fields (mirror of ClaimBase).
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)  # VerificationStatus value
    explanation: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    timestamp: Mapped[float] = mapped_column(Float)  # ms epoch (contract field)
    category: Mapped[str] = mapped_column(String, default="")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    counter_claim: Mapped[str] = mapped_column(Text, default="")
    web_search_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    session: Mapped[Session] = relationship(back_populates="claims")
    segment: Mapped[TranscriptSegment | None] = relationship(back_populates="claims")
