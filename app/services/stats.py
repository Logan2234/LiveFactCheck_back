"""Derived per-session statistics, computed at read time from the child rows.

Nothing here is stored: a session row holds only identity + ``chunks_received``;
everything else (token totals, latencies, claim ratios, cost) is aggregated from
its segments and claims when a ``/sessions`` route is served.
"""

from collections import Counter

from app.models import Session
from app.schemas.history import SessionStats, TokenTotals

# USD per million tokens. VERIFY against current Anthropic pricing before relying
# on the cost estimate — these are indicative and easy to get stale. A model
# absent from this map yields estimated_cost_usd = None rather than a wrong number.
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_write": 1.25,
        "cache_read": 0.1,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.0,
        "output": 5.0,
        "cache_write": 1.25,
        "cache_read": 0.1,
    },
}


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _estimate_cost(model: str, tokens: TokenTotals) -> float | None:
    rates = PRICING.get(model)
    if rates is None:
        return None
    cost = (
        tokens.input * rates["input"]
        + tokens.output * rates["output"]
        + tokens.cache_write * rates["cache_write"]
        + tokens.cache_read * rates["cache_read"]
    ) / 1_000_000
    return round(cost, 6)


def compute_stats(session: Session, model: str) -> SessionStats:
    segments = session.segments
    claims = session.claims

    duration_s: float | None = None
    if session.ended_at is not None:
        duration_s = round((session.ended_at - session.started_at).total_seconds(), 2)

    tokens = TokenTotals(
        input=sum(s.tokens_input or 0 for s in segments),
        output=sum(s.tokens_output or 0 for s in segments),
        cache_read=sum(s.tokens_cache_read or 0 for s in segments),
        cache_write=sum(s.tokens_cache_write or 0 for s in segments),
    )
    tokens.total = tokens.input + tokens.output + tokens.cache_read + tokens.cache_write

    verified_segments = [s for s in segments if s.api_calls is not None]
    segments_with_claims = {c.segment_id for c in claims if c.segment_id is not None}
    rejects = sum(1 for s in verified_segments if s.id not in segments_with_claims)

    categories = [c.category for c in claims if c.category]
    confidences = [c.confidence for c in claims]

    return SessionStats(
        duration_s=duration_s,
        transcripts_count=len(segments),
        claims_count=len(claims),
        claims_by_status=dict(Counter(c.status for c in claims)),
        dominant_category=Counter(categories).most_common(1)[0][0]
        if categories
        else None,
        avg_confidence=_mean([float(c) for c in confidences]),
        segments_verified=len(verified_segments),
        rejects=rejects,
        web_search_segments=sum(1 for s in segments if (s.web_search_calls or 0) > 0),
        web_search_calls_total=sum(s.web_search_calls or 0 for s in segments),
        claims_with_web_search=sum(1 for c in claims if c.web_search_used),
        tokens=tokens,
        api_calls_total=sum(s.api_calls or 0 for s in segments),
        fallback_count=sum(1 for s in segments if (s.api_calls or 0) >= 2),
        avg_transcribe_ms=_mean([s.transcribe_ms for s in segments]),
        avg_verify_ms=_mean([s.verify_ms for s in segments if s.verify_ms is not None]),
        estimated_cost_usd=_estimate_cost(model, tokens),
        pricing_model=model,
    )
