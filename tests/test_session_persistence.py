"""Tests for the lazy session-row creation in session.py.

A connection only gets persisted once it produces a transcript, so an empty
connection (open → close, no speech) leaves no row behind.
"""

import asyncio

from app.services import session
from app.services.session_store import utcnow


def _info() -> dict:
    return {
        "id": "sess-1",
        "client": "127.0.0.1",
        "started_at": utcnow(),
        "persisted": False,
    }


def test_creates_row_once(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        session.session_store,
        "create_session",
        lambda session_id, client, started_at: calls.append(session_id),
    )

    info = _info()
    asyncio.run(session._ensure_persisted(info))
    asyncio.run(session._ensure_persisted(info))  # second call is a no-op

    assert calls == ["sess-1"]
    assert info["persisted"] is True


def test_no_write_when_persistence_disabled(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(session.settings, "PERSIST_SESSIONS", False)
    monkeypatch.setattr(
        session.session_store,
        "create_session",
        lambda *args: calls.append("called"),
    )

    asyncio.run(session._ensure_persisted(_info()))

    assert calls == []
