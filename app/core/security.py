"""Admin authentication primitives: password check + JWT issue/verify.

Pure logic — no FastAPI, no HTTP. The ``require_admin`` dependency that wires
this into routes lives in ``app/dependencies.py``. Single hard-coded admin user;
the password and signing secret come from .env.
"""

import hmac
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

_ALGORITHM = "HS256"
_SUBJECT = "admin"


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


def decode_token(token: str) -> str:
    """Return the token subject, or raise ``jwt.PyJWTError`` if invalid/expired."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[_ALGORITHM])
    return payload.get("sub", _SUBJECT)
