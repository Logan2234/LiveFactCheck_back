"""Admin panel authentication: password check + JWT issue/verify.

Single hard-coded admin user — the password and signing secret come from .env.
Intended for the local admin panel, not multi-user account management.
"""

import hmac
import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_SUBJECT = "admin"
_bearer = HTTPBearer(auto_error=False)


def check_password(password: str) -> bool:
    """Constant-time comparison against the configured admin password."""
    if not settings.ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(password, settings.ADMIN_PASSWORD)


def create_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _SUBJECT,
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGORITHM)


def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """FastAPI dependency: reject the request unless a valid admin JWT is present."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            creds.credentials, settings.JWT_SECRET, algorithms=[_ALGORITHM]
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload.get("sub", _SUBJECT)
