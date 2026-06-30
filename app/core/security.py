"""Authentication primitives: admin password check + JWT issue/verify.

Pure logic — no FastAPI, no HTTP. The ``require_admin`` / ``require_user`` dependencies
that wire this into routes live in ``app/dependencies.py``.

Two token audiences share one signing secret but are kept apart by a ``type`` claim
(``"admin"`` vs ``"user"``): each ``decode_*`` rejects a token of the wrong type, so a
user token can never satisfy an admin-gated route and vice versa.
"""

import hmac
from datetime import UTC, datetime, timedelta

import jwt

from app.config import settings

_ALGORITHM = "HS256"
_ADMIN_SUBJECT = "admin"


def check_password(password: str) -> bool:
    """Constant-time comparison against the configured admin password."""
    if not settings.ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(password, settings.ADMIN_PASSWORD)


def _create_token(subject: str, token_type: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGORITHM)


def _decode(token: str, expected_type: str) -> str:
    """Token subject, or raise ``jwt.PyJWTError`` if invalid/expired/wrong type."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[_ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload.get("sub", "")


def create_token() -> str:
    """Mint an admin JWT."""
    return _create_token(_ADMIN_SUBJECT, "admin")


def decode_token(token: str) -> str:
    """Admin token subject (``"admin"``); raises ``jwt.PyJWTError`` if invalid."""
    return _decode(token, "admin")


def create_user_token(user_id: str) -> str:
    """Mint a user JWT carrying the user id as subject."""
    return _create_token(user_id, "user")


def decode_user_token(token: str) -> str:
    """User id from a user JWT; raises ``jwt.PyJWTError`` if invalid/wrong type."""
    return _decode(token, "user")
