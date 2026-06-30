"""Shared FastAPI dependencies.

The HTTP boundary for auth lives here: it maps a missing/invalid JWT to a 401,
delegating the actual token verification to ``app.core.security``.
"""

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token, decode_user_token

_bearer = HTTPBearer(auto_error=False)


def _require(
    creds: HTTPAuthorizationCredentials | None, decode: Callable[[str], str]
) -> str:
    """Shared bearer-token guard: 401 on a missing/invalid token, else the subject."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode(creds.credentials)
    except jwt.PyJWTError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err


def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Reject the request unless a valid admin JWT is present."""
    return _require(creds, decode_token)


def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Reject the request unless a valid user JWT is present; returns the user id."""
    return _require(creds, decode_user_token)
