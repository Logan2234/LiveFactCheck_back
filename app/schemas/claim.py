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
    """

    type: str = "config"
    language: str
