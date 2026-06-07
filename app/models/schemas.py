from enum import Enum

from pydantic import BaseModel


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FALSE = "false"
    UNCERTAIN = "uncertain"
    UNVERIFIABLE = "unverifiable"


class Claim(BaseModel):
    id: str
    text: str
    status: VerificationStatus = VerificationStatus.PENDING
    explanation: str = ""
    sources: list[str] = []
    timestamp: float = 0.0
    category: str = ""
    confidence: int = 0
    counter_claim: str = ""
    web_search_used: bool = False


class TranscriptMessage(BaseModel):
    type: str = "transcript"
    text: str


class ClaimMessage(BaseModel):
    type: str = "claim"
    claim: Claim
