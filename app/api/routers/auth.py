"""Admin authentication: exchange the admin password for a JWT.

Brute-force protection: failed attempts are counted per client IP and further
attempts are rejected with 429 once the limit is reached. The IP comes from
``request.client.host`` — we deliberately ignore ``X-Forwarded-For`` since this
is a single-instance local service with no reverse proxy in front, and trusting
that header would let an attacker spoof their way around the limit.
"""

from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings
from app.core.rate_limit import LoginRateLimiter
from app.core.security import check_password, create_token
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/admin", tags=["auth"])

_login_limiter = LoginRateLimiter(
    max_attempts=settings.LOGIN_RATE_LIMIT_ATTEMPTS,
    window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
)


@router.post("/login", response_model=TokenResponse)
async def admin_login(req: LoginRequest, request: Request) -> TokenResponse:
    client_ip = request.client.host if request.client else "unknown"

    if _login_limiter.is_blocked(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives, réessayez plus tard",
        )

    if not check_password(req.password):
        _login_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mot de passe incorrect",
        )

    _login_limiter.reset(client_ip)
    return TokenResponse(token=create_token())
