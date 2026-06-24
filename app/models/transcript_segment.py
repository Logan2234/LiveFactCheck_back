"""ORM model for one transcribed utterance and the measurements of its pipeline pass.

A segment maps 1:1 to one pass of the pipeline: one transcription and (if the text
is long enough) one ``extract_and_verify`` call. The per-pass measurements live
here rather than as sums on the session, so session-level totals are plain
aggregates (SUM/AVG) computed at read time.

The measurement columns are NULL when verification did not run (utterance below
``MIN_WORDS``). A segment that has ``api_calls`` set but no linked claims is a
"reject" — verification ran but found no fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.claim import Claim
    from app.models.session import Session


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)  # order of appearance in the session
    text: Mapped[str] = mapped_column(Text)
    detected_language: Mapped[str] = mapped_column(String)
    language_probability: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    # Per-pass measurements. transcribe_ms is always set (transcription always
    # runs for a stored segment); the rest are NULL when extraction didn't run.
    transcribe_ms: Mapped[float] = mapped_column(Float)
    verify_ms: Mapped[float | None] = mapped_column(Float, default=None)
    tokens_input: Mapped[int | None] = mapped_column(Integer, default=None)
    tokens_output: Mapped[int | None] = mapped_column(Integer, default=None)
    tokens_cache_read: Mapped[int | None] = mapped_column(Integer, default=None)
    tokens_cache_write: Mapped[int | None] = mapped_column(Integer, default=None)
    api_calls: Mapped[int | None] = mapped_column(Integer, default=None)  # 1 or 2
    web_search_calls: Mapped[int | None] = mapped_column(Integer, default=None)

    session: Mapped[Session] = relationship(back_populates="segments")
    claims: Mapped[list[Claim]] = relationship(back_populates="segment")
