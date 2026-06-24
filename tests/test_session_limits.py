"""Integration tests for the public-beta /ws guardrails in session.py.

Two independent caps, both off by default (0):
- MAX_CONCURRENT_SESSIONS: a new connection past the cap is refused before the
  handshake with WS close 1013.
- MAX_SESSION_DURATION_SECONDS: an open connection is force-closed with WS close
  4000 once it outlives the cap.

These drive the real ``run_session`` over a TestClient WebSocket. The duration
test stubs the endpointer so no Whisper/Silero model is loaded (no audio is sent,
so the dummy is never actually exercised).
"""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.services import session

client = TestClient(app)


class _DummyEndpointer:
    """Stand-in so run_session needn't build the real VAD endpointer in tests."""

    def add(self, samples: object) -> None:
        pass

    def pop(self):
        return None


def test_rejects_connection_at_capacity(monkeypatch) -> None:
    # Two slots, both already taken: the next connection must be refused.
    monkeypatch.setattr(session.settings, "MAX_CONCURRENT_SESSIONS", 2)
    monkeypatch.setattr(session, "_active_sessions", {"a": {}, "b": {}})

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws"),
    ):
        pass

    assert exc_info.value.code == 1013


def test_accepts_connection_below_capacity(monkeypatch) -> None:
    # One slot free: the connection is accepted (no rejection raised on enter).
    monkeypatch.setattr(session.settings, "MAX_CONCURRENT_SESSIONS", 2)
    monkeypatch.setattr(session, "_active_sessions", {"a": {}})
    monkeypatch.setattr(session, "_make_endpointer", lambda: _DummyEndpointer())

    with client.websocket_connect("/ws") as ws:
        # Accepted: the socket is open. Close from our side to end cleanly.
        ws.close()


def test_disabled_capacity_never_rejects(monkeypatch) -> None:
    # 0 = disabled: even with sessions registered, a new one is accepted.
    monkeypatch.setattr(session.settings, "MAX_CONCURRENT_SESSIONS", 0)
    monkeypatch.setattr(session, "_active_sessions", {"a": {}, "b": {}, "c": {}})
    monkeypatch.setattr(session, "_make_endpointer", lambda: _DummyEndpointer())

    with client.websocket_connect("/ws") as ws:
        ws.close()


def test_closes_session_after_duration_cap(monkeypatch) -> None:
    # 1 s cap: an idle connection (no audio sent) is force-closed with code 4000.
    monkeypatch.setattr(session.settings, "MAX_CONCURRENT_SESSIONS", 0)
    monkeypatch.setattr(session.settings, "MAX_SESSION_DURATION_SECONDS", 1)
    monkeypatch.setattr(session, "_make_endpointer", lambda: _DummyEndpointer())

    with client.websocket_connect("/ws") as ws:
        # Raw receive() surfaces the server's close frame as a message dict.
        message = ws.receive()

    assert message["type"] == "websocket.close"
    assert message["code"] == 4000
