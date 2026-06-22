"""Pydantic schemas for claims — the WebSocket/API contract.

Mirrored front-side by the ``Claim`` shape in ``front/src/lib/stores/claims.ts``.
Any change here is a two-repo change (see ../../CLAUDE.md).
"""

from enum import StrEnum

from pydantic import BaseModel


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    FALSE = "false"
    UNCERTAIN = "uncertain"
    UNVERIFIABLE = "unverifiable"


class VerificationLevel(StrEnum):
    """How thoroughly a session verifies claims (speed vs depth trade-off).

    ``FAST`` checks against the model's internal knowledge only (no web_search
    tool offered, so a single quick API call). ``THOROUGH`` makes web_search
    available, letting the model look up recent/changing facts at the cost of
    extra latency. ``THOROUGH`` is the default — it preserves prior behaviour.
    """

    FAST = "fast"
    THOROUGH = "thorough"


class ClaimBase(BaseModel):
    text: str
    status: VerificationStatus = VerificationStatus.PENDING
    explanation: str = ""
    sources: list[str] = []
    timestamp: float = 0.0
    category: str = ""
    confidence: int = 0
    counter_claim: str = ""
    web_search_used: bool = False


class Claim(ClaimBase):
    id: str


class TranscriptMessage(BaseModel):
    type: str = "transcript"
    text: str
    # The language Whisper detected for this chunk and its probability.
    # Always present: transcription always runs in auto-detect mode.
    language: str
    language_probability: float


class ClaimMessage(BaseModel):
    type: str = "claim"
    claim: Claim


class ConfigMessage(BaseModel):
    """Client → server session config (sent as a text frame on the socket).

    ``language`` is the ``"auto"`` sentinel or an ISO code; it is normalized
    against the supported set when applied (an unknown code falls back to auto).
    ``verification_level`` picks the speed/depth trade-off; it defaults to
    ``THOROUGH`` so an older client that omits it keeps the previous behaviour.
    """

    type: str = "config"
    language: str
    verification_level: VerificationLevel = VerificationLevel.THOROUGH
