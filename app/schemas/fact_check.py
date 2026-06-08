"""Request/response schemas for fact-checking routes (prod + debug)."""

from pydantic import BaseModel

from app.schemas.claim import Claim


class FactCheckRequest(BaseModel):
    text: str
    web_search: bool = True


class FactCheckResponse(BaseModel):
    text: str
    claims: list[Claim]


class ModelTestRequest(BaseModel):
    text: str
    web_search: bool = True


class ModelTestUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0


class ModelTestResponse(BaseModel):
    claims: list[Claim]
    turns: int
    usage: ModelTestUsage | dict
    model: str
    web_search_enabled: bool
    web_search_called: bool
