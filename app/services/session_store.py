"""Write-side persistence for live sessions (transcripts, claims, metrics).

These are plain synchronous SQLAlchemy helpers. The WebSocket path is async, so it
calls them through ``asyncio.to_thread`` (see ``services/session.py``). Each helper
opens its own short-lived ``Session`` and commits, which keeps SQLite write locks
brief — fine for the single live connection this app serves.

Reads (the ``/sessions`` routes) don't go through here; they use the ``get_db``
dependency directly.
"""

from datetime import UTC, datetime

from app.db.session import SessionLocal
from app.models import Claim, Session, TranscriptSegment


def utcnow() -> datetime:
    """Naive UTC timestamp, so all stored datetimes are comparable."""
    return datetime.now(UTC).replace(tzinfo=None)


def create_session(session_id: str, client_host: str, started_at: datetime) -> None:
    with SessionLocal() as db:
        db.add(
            Session(
                id=session_id,
                started_at=started_at,
                client_host=client_host,
            )
        )
        db.commit()


def end_session(session_id: str, ended_at: datetime, chunks_received: int) -> None:
    with SessionLocal() as db:
        session = db.get(Session, session_id)
        if session is None:
            return
        session.ended_at = ended_at
        session.chunks_received = chunks_received
        db.commit()


def add_segment(
    *,
    segment_id: str,
    session_id: str,
    seq: int,
    text: str,
    detected_language: str,
    language_probability: float,
    transcribe_ms: float,
) -> None:
    with SessionLocal() as db:
        db.add(
            TranscriptSegment(
                id=segment_id,
                session_id=session_id,
                seq=seq,
                text=text,
                detected_language=detected_language,
                language_probability=language_probability,
                created_at=utcnow(),
                transcribe_ms=transcribe_ms,
            )
        )
        db.commit()


def set_segment_metrics(
    segment_id: str,
    *,
    verify_ms: float,
    usage: dict[str, int],
    api_calls: int,
    web_search_calls: int,
) -> None:
    """Fill in the verification measurements once the background task completes."""
    with SessionLocal() as db:
        segment = db.get(TranscriptSegment, segment_id)
        if segment is None:
            return
        segment.verify_ms = verify_ms
        segment.tokens_input = usage.get("input_tokens", 0)
        segment.tokens_output = usage.get("output_tokens", 0)
        segment.tokens_cache_read = usage.get("cache_read", 0)
        segment.tokens_cache_write = usage.get("cache_write", 0)
        segment.api_calls = api_calls
        segment.web_search_calls = web_search_calls
        db.commit()


def add_claim(claim: dict, session_id: str, segment_id: str | None) -> None:
    """Persist a verified claim from its WS ``model_dump`` dict (final state only)."""
    with SessionLocal() as db:
        db.add(
            Claim(
                id=claim["id"],
                session_id=session_id,
                segment_id=segment_id,
                text=claim["text"],
                status=claim["status"],
                explanation=claim["explanation"],
                sources=claim["sources"],
                timestamp=claim["timestamp"],
                category=claim["category"],
                confidence=claim["confidence"],
                counter_claim=claim["counter_claim"],
                web_search_used=claim["web_search_used"],
                created_at=utcnow(),
            )
        )
        db.commit()
