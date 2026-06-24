"""Tests for the per-session claim dedup helper in session.py."""

from collections import OrderedDict

from app.services import session
from app.services.session import _dedupe_claims


def _claim(text: str) -> dict:
    return {"text": text, "status": "verified"}


def test_keeps_distinct_claims() -> None:
    seen: OrderedDict[str, None] = OrderedDict()
    kept = _dedupe_claims([_claim("Paris en France"), _claim("Rome en Italie")], seen)
    assert [c["text"] for c in kept] == ["Paris en France", "Rome en Italie"]


def test_drops_already_seen_claim() -> None:
    seen: OrderedDict[str, None] = OrderedDict()
    _dedupe_claims([_claim("Paris est en France.")], seen)
    # Same fact, different casing/punctuation → normalized to the same key, dropped.
    kept = _dedupe_claims([_claim("paris est en france")], seen)
    assert kept == []


def test_dedupes_within_a_single_batch() -> None:
    seen: OrderedDict[str, None] = OrderedDict()
    kept = _dedupe_claims(
        [_claim("Le ciel est bleu"), _claim("le ciel est bleu")], seen
    )
    assert len(kept) == 1


def test_registry_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(session, "SEEN_CLAIMS_MAX", 2)
    seen: OrderedDict[str, None] = OrderedDict()
    _dedupe_claims([_claim("un"), _claim("deux"), _claim("trois")], seen)
    # Oldest evicted past the bound: only the last two keys remain.
    assert list(seen.keys()) == ["deux", "trois"]
