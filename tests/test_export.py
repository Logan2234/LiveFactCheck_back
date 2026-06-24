"""Unit tests for the Markdown session export (pure formatting)."""

from datetime import datetime

from app.schemas.history import (
    ClaimOut,
    SegmentOut,
    SessionDetail,
    SessionStats,
    TokenTotals,
)
from app.services.export import session_to_markdown


def _detail() -> SessionDetail:
    return SessionDetail(
        id="abc",
        started_at=datetime(2026, 1, 1, 10, 0, 0),
        ended_at=datetime(2026, 1, 1, 10, 0, 30),
        active=False,
        client_host="127.0.0.1",
        chunks_received=10,
        stats=SessionStats(
            duration_s=30.0,
            transcripts_count=2,
            claims_count=1,
            claims_by_status={"false": 1},
            dominant_category="science",
            avg_confidence=6.0,
            tokens=TokenTotals(input=100, output=50, total=150),
            estimated_cost_usd=0.0001,
            pricing_model="claude-haiku-4-5",
        ),
        segments=[
            SegmentOut(
                id="seg1",
                seq=0,
                text="La Terre est plate.",
                detected_language="fr",
                language_probability=0.99,
                created_at=datetime(2026, 1, 1, 10, 0, 1),
                transcribe_ms=12.0,
            )
        ],
        claims=[
            ClaimOut(
                id="c1",
                segment_id="seg1",
                text="La Terre est plate.",
                status="false",
                explanation="La Terre est un géoïde.",
                sources=["https://example.com"],
                timestamp=0.0,
                category="science",
                confidence=6,
                counter_claim="La Terre est sphérique.",
                web_search_used=True,
                created_at=datetime(2026, 1, 1, 10, 0, 2),
            )
        ],
    )


def test_markdown_includes_header_and_stats() -> None:
    md = session_to_markdown(_detail())
    assert "# LiveFactChecker — session abc" in md
    assert "Duration**: 30.0 s" in md
    assert "Claims: 1 (false 1)" in md
    assert "Estimated cost: $0.0001 (claude-haiku-4-5)" in md


def test_markdown_includes_claim_and_correction() -> None:
    md = session_to_markdown(_detail())
    assert "### [false] La Terre est plate." in md
    assert "**Correction**: La Terre est sphérique." in md
    assert "Source: https://example.com" in md


def test_markdown_includes_transcript() -> None:
    md = session_to_markdown(_detail())
    assert "## Transcript" in md
    assert "1. (fr) La Terre est plate." in md


def test_markdown_handles_empty_claims() -> None:
    detail = _detail()
    detail.claims = []
    md = session_to_markdown(detail)
    assert "_No claims._" in md
