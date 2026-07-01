"""Tests for the per-utterance claim cycle in session.py.

Covers the pieces the dedup/persistence tests don't:
- ``_make_claim``: result dict → ``Claim`` mapping.
- ``_spawn_claims``: skips a transcript under ``MIN_WORDS``, otherwise fires a task.
- ``_process_claims``: the pending → claim(s) / remove_claim lifecycle.

Everything runs in isolation — ``extract_and_verify`` is mocked, the WebSocket is a
fake that records ``send_json`` payloads, and persistence is turned off so no DB or
webhook is touched.
"""

import asyncio
from collections import OrderedDict

import pytest

from app.services import session
from app.services.claim_extractor import MIN_WORDS, ExtractResult
from app.services.session import _make_claim, _process_claims, _spawn_claims


class FakeWebSocket:
    """Minimal stand-in: records every JSON frame the session sends."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _no_persistence(monkeypatch) -> None:
    # Keep _process_claims off the DB: _persist short-circuits when this is False.
    monkeypatch.setattr(session.settings, "PERSIST_SESSIONS", False)


def _mock_extract(monkeypatch, claims: list[dict]) -> None:
    async def _fake(transcript, context, web_search):
        return ExtractResult(claims=claims)

    monkeypatch.setattr(session, "extract_and_verify", _fake)


# --- _make_claim ----------------------------------------------------------------


def test_make_claim_maps_all_fields() -> None:
    result = {
        "text": "La Terre est plate.",
        "status": "false",
        "explanation": "La Terre est un géoïde.",
        "sources": ["https://example.com"],
        "category": "science",
        "confidence": 6,
        "counter_claim": "La Terre est sphérique.",
        "web_search_used": True,
    }
    claim = _make_claim(result, "claim-1", 1234)

    assert claim.id == "claim-1"
    assert claim.text == "La Terre est plate."
    assert claim.status.value == "false"
    assert claim.timestamp == 1234
    assert claim.sources == ["https://example.com"]
    assert claim.category == "science"
    assert claim.confidence == 6
    assert claim.counter_claim == "La Terre est sphérique."
    assert claim.web_search_used is True


def test_make_claim_uses_defaults_for_optional_fields() -> None:
    claim = _make_claim({"text": "x", "status": "verified", "explanation": ""}, "id", 0)
    assert claim.sources == []
    assert claim.category == ""
    assert claim.confidence == 0
    assert claim.web_search_used is False


# --- _spawn_claims --------------------------------------------------------------


def _session_info() -> dict:
    return {
        "id": "sess-1",
        "claims_spawned": 0,
        "verification_level": session.VerificationLevel.FAST,
        "seen_claims": OrderedDict(),
        "webhooks": [],
    }


def test_spawn_skips_transcript_under_min_words() -> None:
    info = _session_info()
    tasks: set = set()
    short = " ".join(["mot"] * (MIN_WORDS - 1))

    _spawn_claims(FakeWebSocket(), short, [], tasks, info, "seg-1")

    assert info["claims_spawned"] == 0
    assert tasks == set()


def test_spawn_fires_task_when_long_enough(monkeypatch) -> None:
    _mock_extract(monkeypatch, claims=[])
    info = _session_info()
    long = " ".join(["mot"] * MIN_WORDS)

    async def _run() -> None:
        tasks: set = set()
        _spawn_claims(FakeWebSocket(), long, [], tasks, info, "seg-1")
        assert info["claims_spawned"] == 1
        assert len(tasks) == 1
        await asyncio.gather(*tasks)

    asyncio.run(_run())


# --- _process_claims lifecycle --------------------------------------------------


def _process(ws: FakeWebSocket) -> None:
    asyncio.run(
        _process_claims(
            ws,
            transcript="La Terre est plate.",
            context=[],
            web_search=False,
            session_id="sess-1",
            segment_id="seg-1",
            seen_claims=OrderedDict(),
            webhooks=[],
        )
    )


def _verified(text: str) -> dict:
    return {"text": text, "status": "false", "explanation": "..."}


def test_pending_then_verified_claim_reuses_id(monkeypatch) -> None:
    _mock_extract(monkeypatch, claims=[_verified("La Terre est plate.")])
    ws = FakeWebSocket()
    _process(ws)

    assert [m["type"] for m in ws.sent] == ["claim", "claim"]
    pending, verified = ws.sent
    assert pending["claim"]["status"] == "pending"
    # The verified claim replaces the placeholder in-place: same id, real status.
    assert verified["claim"]["id"] == pending["claim"]["id"]
    assert verified["claim"]["status"] == "false"


def test_no_claim_removes_pending(monkeypatch) -> None:
    _mock_extract(monkeypatch, claims=[])
    ws = FakeWebSocket()
    _process(ws)

    assert [m["type"] for m in ws.sent] == ["claim", "remove_claim"]
    pending, removal = ws.sent
    assert pending["claim"]["status"] == "pending"
    assert removal["id"] == pending["claim"]["id"]


def test_extra_claims_get_fresh_ids(monkeypatch) -> None:
    _mock_extract(
        monkeypatch, claims=[_verified("Premier fait."), _verified("Second fait.")]
    )
    ws = FakeWebSocket()
    _process(ws)

    # pending, first (reusing the pending id), then one extra with a new id.
    assert [m["type"] for m in ws.sent] == ["claim", "claim", "claim"]
    pending_id = ws.sent[0]["claim"]["id"]
    assert ws.sent[1]["claim"]["id"] == pending_id
    assert ws.sent[2]["claim"]["id"] != pending_id
    assert ws.sent[2]["claim"]["text"] == "Second fait."
