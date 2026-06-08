"""Prod fact-checking route (admin-gated).

The HTTP layer only validates input, calls the service, and serializes out;
all extraction/verification logic lives in ``app.services.claim_extractor``.
"""

from fastapi import APIRouter, Depends

from app.dependencies import require_admin
from app.schemas.claim import Claim
from app.schemas.fact_check import FactCheckRequest, FactCheckResponse
from app.services.claim_extractor import extract_and_verify

router = APIRouter(tags=["fact-check"])


@router.post("/fact-check", response_model=FactCheckResponse)
async def fact_check(
    req: FactCheckRequest, _admin: str = Depends(require_admin)
) -> FactCheckResponse:
    results = await extract_and_verify(req.text, web_search=req.web_search)
    # Service dicts carry every Claim field except id/timestamp; the response
    # model fills those with defaults. This route is diagnostic, not the live
    # WS path, so stable ids/timestamps aren't needed here.
    claims = [Claim(id="", **r) for r in results]
    return FactCheckResponse(text=req.text, claims=claims)
