"""Integration tests for the /sessions read & export routes.

Overrides ``get_db`` with a shared in-memory SQLite so the routes hit a seeded
test database instead of the real file.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.dependencies import require_admin
from app.main import app
from app.models import Claim, Session, TranscriptSegment

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # one shared connection so the in-memory DB persists
)
_TestSession = sessionmaker(bind=_engine, expire_on_commit=False)
Base.metadata.create_all(_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed() -> None:
    # These routes are admin-gated; bypass the JWT check per test (another test
    # module pops this override in its teardown, so set it fresh each time).
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    with _TestSession() as db:
        db.query(Claim).delete()
        db.query(TranscriptSegment).delete()
        db.query(Session).delete()
        session = Session(
            id="sess-1",
            started_at=datetime(2026, 1, 1, 10, 0, 0),
            ended_at=datetime(2026, 1, 1, 10, 0, 20),
            client_host="127.0.0.1",
            chunks_received=5,
        )
        session.segments = [
            TranscriptSegment(
                id="seg-1",
                session_id="sess-1",
                seq=0,
                text="La Terre est plate.",
                detected_language="fr",
                language_probability=0.99,
                created_at=datetime(2026, 1, 1, 10, 0, 1),
                transcribe_ms=12.0,
                verify_ms=120.0,
                tokens_input=100,
                tokens_output=50,
                tokens_cache_read=0,
                tokens_cache_write=0,
                api_calls=1,
                web_search_calls=0,
            )
        ]
        session.claims = [
            Claim(
                id="claim-1",
                session_id="sess-1",
                segment_id="seg-1",
                text="La Terre est plate.",
                status="false",
                explanation="La Terre est un géoïde.",
                sources=["https://example.com"],
                timestamp=1.0,
                category="science",
                confidence=6,
                counter_claim="La Terre est sphérique.",
                web_search_used=False,
                created_at=datetime(2026, 1, 1, 10, 0, 2),
            )
        ]
        db.add(session)
        db.commit()


def test_routes_require_admin() -> None:
    # Drop the auth override to confirm the routes are actually gated. The autouse
    # fixture re-adds it before the next test.
    app.dependency_overrides.pop(require_admin, None)
    assert client.get("/sessions").status_code == 401
    assert client.get("/sessions/sess-1").status_code == 401
    assert client.get("/sessions/sess-1/export").status_code == 401


def test_list_sessions() -> None:
    resp = client.get("/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "sess-1"
    assert body[0]["claims_count"] == 1
    assert body[0]["false_count"] == 1
    assert body[0]["active"] is False


def test_get_session_detail() -> None:
    resp = client.get("/sessions/sess-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stats"]["claims_count"] == 1
    assert body["stats"]["tokens"]["total"] == 150
    assert len(body["segments"]) == 1
    assert len(body["claims"]) == 1


def test_get_unknown_session_is_404() -> None:
    assert client.get("/sessions/nope").status_code == 404


def test_export_markdown() -> None:
    resp = client.get("/sessions/sess-1/export", params={"format": "md"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "session-sess-1.md" in resp.headers["content-disposition"]
    assert "### [false] La Terre est plate." in resp.text


def test_export_json_is_default() -> None:
    resp = client.get("/sessions/sess-1/export")
    assert resp.status_code == 200
    assert "session-sess-1.json" in resp.headers["content-disposition"]
    assert resp.json()["id"] == "sess-1"
