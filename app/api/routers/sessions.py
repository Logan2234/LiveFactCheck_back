"""Session history & export (read-only, admin-gated).

Browsing past sessions is an admin capability: there is no per-user notion, so the
whole history is global and sits behind ``require_admin``. A regular user exporting
their *own live* session is a separate, client-side path (built from the in-browser
stores), not these routes.

Handlers are plain ``def`` so FastAPI runs them in its threadpool — the sync
SQLAlchemy session from ``get_db`` never blocks the event loop.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.db.session import get_db
from app.dependencies import require_admin
from app.models import Session
from app.schemas.history import ClaimOut, SegmentOut, SessionDetail, SessionSummary
from app.services.export import session_to_markdown
from app.services.stats import compute_stats

router = APIRouter(
    prefix="/sessions", tags=["sessions"], dependencies=[Depends(require_admin)]
)


def _summary(session: Session, model: str) -> SessionSummary:
    stats = compute_stats(session, model)
    return SessionSummary(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        active=session.ended_at is None,
        client_host=session.client_host,
        transcripts_count=stats.transcripts_count,
        claims_count=stats.claims_count,
        false_count=stats.claims_by_status.get("false", 0),
        estimated_cost_usd=stats.estimated_cost_usd,
    )


def _detail(session: Session, model: str) -> SessionDetail:
    return SessionDetail(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        active=session.ended_at is None,
        client_host=session.client_host,
        chunks_received=session.chunks_received,
        stats=compute_stats(session, model),
        # Explicit ORM → schema conversion (segments come ordered by seq).
        segments=[SegmentOut.model_validate(s) for s in session.segments],
        claims=[
            ClaimOut.model_validate(c)
            for c in sorted(session.claims, key=lambda c: c.timestamp)
        ],
    )


def _get_or_404(db: DBSession, session_id: str) -> Session:
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session introuvable")
    return session


@router.get("", response_model=list[SessionSummary])
def list_sessions(
    db: DBSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[SessionSummary]:
    sessions = (
        db.execute(select(Session).order_by(Session.started_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    model = settings.ANTHROPIC_MODEL
    return [_summary(s, model) for s in sessions]


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, db: DBSession = Depends(get_db)) -> SessionDetail:
    return _detail(_get_or_404(db, session_id), settings.ANTHROPIC_MODEL)


@router.get("/{session_id}/export", response_model=None)
def export_session(
    session_id: str,
    db: DBSession = Depends(get_db),
    fmt: Literal["json", "md"] = Query(default="json", alias="format"),
) -> JSONResponse | PlainTextResponse:
    detail = _detail(_get_or_404(db, session_id), settings.ANTHROPIC_MODEL)
    if fmt == "md":
        return PlainTextResponse(
            session_to_markdown(detail),
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="session-{session_id}.md"'
            },
        )
    return JSONResponse(
        detail.model_dump(mode="json"),
        headers={
            "Content-Disposition": f'attachment; filename="session-{session_id}.json"'
        },
    )
