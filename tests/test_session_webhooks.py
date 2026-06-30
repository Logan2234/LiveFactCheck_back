"""Tests for per-session webhook delivery wiring in session.py.

Covers the two pieces added for Phase 4, in isolation (no DB, no real WebSocket):
- ``_resolve_user_webhooks``: token → (user_id, snapshot); else → (None, []).
- ``_deliver_webhooks``: fires only webhooks matching the claim status, records
  delivery health, and never raises.
"""

import asyncio

from app.core.security import create_user_token
from app.services import session


def _webhook(wid: str, statuses: list[str]) -> dict:
    return {
        "id": wid,
        "url": f"https://example.test/{wid}",
        "kind": "custom",
        "secret": f"secret-{wid}",
        "trigger_statuses": statuses,
    }


# --- _deliver_webhooks ----------------------------------------------------------


def test_deliver_fires_only_matching_status(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        session.webhook,
        "deliver",
        lambda url, kind, claim, session_id, secret: calls.append(
            (url, kind, claim, session_id, secret)
        ),
    )
    recorded: list[tuple] = []
    monkeypatch.setattr(
        session,
        "_record_delivery_sync",
        lambda wid, ok, err: recorded.append((wid, ok, err)),
    )

    webhooks = [_webhook("w1", ["false"]), _webhook("w2", ["uncertain"])]
    claim = {"id": "c1", "status": "false", "text": "La Terre est plate"}
    asyncio.run(session._deliver_webhooks(webhooks, claim, "sess-1"))

    # Only w1 (trigger "false") fires, with its kind, the claim, session id and secret.
    assert [c[0] for c in calls] == ["https://example.test/w1"]
    assert calls[0][1] == "custom"
    assert calls[0][2] == claim
    assert calls[0][3] == "sess-1"
    assert calls[0][4] == "secret-w1"
    assert recorded == [("w1", True, None)]


def test_deliver_noop_without_webhooks(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(session.webhook, "deliver", lambda *a, **k: calls.append(1))
    asyncio.run(session._deliver_webhooks([], {"status": "false"}, "sess-1"))
    assert calls == []


def test_deliver_records_failure(monkeypatch) -> None:
    # deliver returns an error string → recorded as a failure.
    monkeypatch.setattr(
        session.webhook,
        "deliver",
        lambda url, kind, claim, session_id, secret: "boom",
    )
    recorded: list[tuple] = []
    monkeypatch.setattr(
        session,
        "_record_delivery_sync",
        lambda wid, ok, err: recorded.append((wid, ok, err)),
    )

    webhooks = [_webhook("w1", ["false"])]
    asyncio.run(
        session._deliver_webhooks(webhooks, {"id": "c", "status": "false"}, "sess-1")
    )
    assert recorded == [("w1", False, "boom")]


# --- _resolve_user_webhooks -----------------------------------------------------


def test_resolve_without_token_is_anonymous() -> None:
    assert asyncio.run(session._resolve_user_webhooks(None)) == (None, [])


def test_resolve_with_invalid_token_is_anonymous() -> None:
    assert asyncio.run(session._resolve_user_webhooks("not-a-jwt")) == (None, [])


def test_resolve_with_valid_token_loads_snapshot(monkeypatch) -> None:
    token = create_user_token("user-x")
    snapshot = [_webhook("w1", ["false"])]
    monkeypatch.setattr(session, "_load_webhooks_sync", lambda uid: snapshot)

    user_id, webhooks = asyncio.run(session._resolve_user_webhooks(token))
    assert user_id == "user-x"
    assert webhooks == snapshot
