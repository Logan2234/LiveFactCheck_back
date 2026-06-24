"""Unit tests for the derived per-session statistics (pure, no DB).

Builds transient ORM instances in memory and checks that ``compute_stats``
aggregates them correctly — token sums, latencies, reject detection, cost.
"""

from datetime import datetime

from app.models import Claim, Session, TranscriptSegment
from app.services.stats import compute_stats


def _seg(
    seg_id: str,
    seq: int,
    *,
    transcribe_ms: float = 10.0,
    verify_ms: float | None = None,
    ti: int | None = None,
    to: int | None = None,
    cr: int | None = None,
    cw: int | None = None,
    api: int | None = None,
    web: int | None = None,
) -> TranscriptSegment:
    return TranscriptSegment(
        id=seg_id,
        session_id="s",
        seq=seq,
        text="t",
        detected_language="fr",
        language_probability=0.9,
        created_at=datetime(2026, 1, 1),
        transcribe_ms=transcribe_ms,
        verify_ms=verify_ms,
        tokens_input=ti,
        tokens_output=to,
        tokens_cache_read=cr,
        tokens_cache_write=cw,
        api_calls=api,
        web_search_calls=web,
    )


def _claim(
    claim_id: str,
    *,
    status: str = "verified",
    confidence: int = 8,
    segment_id: str = "seg1",
    web: bool = False,
) -> Claim:
    return Claim(
        id=claim_id,
        session_id="s",
        segment_id=segment_id,
        text="c",
        status=status,
        explanation="",
        sources=[],
        timestamp=0.0,
        category="science",
        confidence=confidence,
        counter_claim="",
        web_search_used=web,
        created_at=datetime(2026, 1, 1),
    )


def _session() -> Session:
    session = Session(
        id="s",
        started_at=datetime(2026, 1, 1, 10, 0, 0),
        ended_at=datetime(2026, 1, 1, 10, 0, 30),
        client_host="127.0.0.1",
        chunks_received=42,
    )
    session.segments = [
        _seg("seg1", 0, verify_ms=100, ti=100, to=50, cr=10, cw=5, api=1, web=0),
        _seg("seg2", 1, verify_ms=200, ti=200, to=20, cr=0, cw=0, api=2, web=1),
        _seg("seg3", 2, verify_ms=50, ti=10, to=5, cr=0, cw=0, api=1, web=0),
        _seg("seg4", 3),  # too short: extraction never ran (metrics NULL)
    ]
    session.claims = [
        _claim("c1", status="verified", confidence=8, segment_id="seg1"),
        _claim("c2", status="false", confidence=6, segment_id="seg2", web=True),
    ]
    return session


def test_counts_and_ratios() -> None:
    stats = compute_stats(_session(), "claude-haiku-4-5")

    assert stats.duration_s == 30.0
    assert stats.transcripts_count == 4
    assert stats.claims_count == 2
    assert stats.claims_by_status == {"verified": 1, "false": 1}
    assert stats.dominant_category == "science"
    assert stats.avg_confidence == 7.0


def test_verification_and_reject_detection() -> None:
    stats = compute_stats(_session(), "claude-haiku-4-5")

    # seg1, seg2, seg3 ran verification; seg3 produced no claim → one reject.
    assert stats.segments_verified == 3
    assert stats.rejects == 1
    assert stats.api_calls_total == 4
    assert stats.fallback_count == 1  # seg2 needed two turns


def test_web_search_and_latency() -> None:
    stats = compute_stats(_session(), "claude-haiku-4-5")

    assert stats.web_search_segments == 1
    assert stats.web_search_calls_total == 1
    assert stats.claims_with_web_search == 1
    assert stats.avg_transcribe_ms == 10.0
    assert stats.avg_verify_ms == round((100 + 200 + 50) / 3, 2)


def test_token_totals() -> None:
    stats = compute_stats(_session(), "claude-haiku-4-5")

    assert stats.tokens.input == 310
    assert stats.tokens.output == 75
    assert stats.tokens.cache_read == 10
    assert stats.tokens.cache_write == 5
    assert stats.tokens.total == 400


def test_cost_estimate_for_known_model() -> None:
    stats = compute_stats(_session(), "claude-haiku-4-5")
    # 310*1 + 75*5 + 5*1.25 + 10*0.1 = 692.25 USD per million tokens.
    assert stats.estimated_cost_usd == round(692.25 / 1_000_000, 6)
    assert stats.pricing_model == "claude-haiku-4-5"


def test_cost_is_none_for_unknown_model() -> None:
    stats = compute_stats(_session(), "some-unpriced-model")
    assert stats.estimated_cost_usd is None


def test_active_session_has_no_duration() -> None:
    session = _session()
    session.ended_at = None
    stats = compute_stats(session, "claude-haiku-4-5")
    assert stats.duration_s is None
