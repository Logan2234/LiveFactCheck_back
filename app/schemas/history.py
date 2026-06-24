"""Read-side schemas for the /sessions history & export routes.

These serialize the ORM models in ``app/models/`` out to the API. ``from_attributes``
lets them be built straight from an ORM instance; aggregate stats are computed by
``app.services.stats`` and attached, never stored.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TokenTotals(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total: int = 0


class SessionStats(BaseModel):
    """Everything derived from a session's segments and claims at read time."""

    duration_s: float | None = None
    transcripts_count: int = 0
    claims_count: int = 0
    claims_by_status: dict[str, int] = {}
    dominant_category: str | None = None
    avg_confidence: float | None = None
    # Segments where verification ran (api_calls set), and those that ran but
    # yielded no claim (a "reject" — remove_claim live).
    segments_verified: int = 0
    rejects: int = 0
    # web_search reach: segments that searched, total searches, claims that used it.
    web_search_segments: int = 0
    web_search_calls_total: int = 0
    claims_with_web_search: int = 0
    tokens: TokenTotals = TokenTotals()
    api_calls_total: int = 0
    fallback_count: int = 0  # segments that needed the two-turn fallback
    avg_transcribe_ms: float | None = None
    avg_verify_ms: float | None = None
    # Rough cost estimate using ``pricing_model``'s rates; None if that model
    # has no known pricing. The model is the one configured now, which may differ
    # from the one used during the session.
    estimated_cost_usd: float | None = None
    pricing_model: str = ""


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    segment_id: str | None = None
    text: str
    status: str
    explanation: str
    sources: list[str]
    timestamp: float
    category: str
    confidence: int
    counter_claim: str
    web_search_used: bool
    created_at: datetime


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    seq: int
    text: str
    detected_language: str
    language_probability: float
    created_at: datetime
    transcribe_ms: float
    verify_ms: float | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    tokens_cache_read: int | None = None
    tokens_cache_write: int | None = None
    api_calls: int | None = None
    web_search_calls: int | None = None


class SessionSummary(BaseModel):
    """Compact row for the session list."""

    id: str
    started_at: datetime
    ended_at: datetime | None = None
    active: bool
    client_host: str
    transcripts_count: int
    claims_count: int
    false_count: int
    estimated_cost_usd: float | None = None


class SessionDetail(BaseModel):
    """Full session: identity, derived stats, transcript and claims."""

    id: str
    started_at: datetime
    ended_at: datetime | None = None
    active: bool
    client_host: str
    chunks_received: int
    stats: SessionStats
    segments: list[SegmentOut]
    claims: list[ClaimOut]
