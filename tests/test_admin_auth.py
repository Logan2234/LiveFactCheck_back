"""Tests for admin JWT issue/verify and the ``require_admin`` HTTP guard.

``test_auth_route`` already covers the /admin/login endpoint (correct password → token,
wrong → 401, brute-force limiting). This module covers the token itself: the round-trip,
expiry, and how ``require_admin`` maps a missing/invalid/expired token to a 401. The
guard is tested directly (no TestClient) since it's pure dependency logic.
"""

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core import security
from app.core.security import create_token, decode_token
from app.dependencies import require_admin


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_token_round_trip() -> None:
    assert decode_token(create_token()) == "admin"


def test_expired_token_is_rejected(monkeypatch) -> None:
    # Mint a token that expired an hour ago, then confirm decode refuses it.
    monkeypatch.setattr(security.settings, "JWT_EXPIRE_HOURS", -1)
    token = create_token()
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)


def test_require_admin_accepts_valid_token() -> None:
    assert require_admin(_creds(create_token())) == "admin"


def test_require_admin_rejects_missing_token() -> None:
    with pytest.raises(HTTPException) as exc:
        require_admin(None)
    assert exc.value.status_code == 401


def test_require_admin_rejects_garbage_token() -> None:
    with pytest.raises(HTTPException) as exc:
        require_admin(_creds("not-a-jwt"))
    assert exc.value.status_code == 401


def test_require_admin_rejects_expired_token(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "JWT_EXPIRE_HOURS", -1)
    expired = create_token()
    with pytest.raises(HTTPException) as exc:
        require_admin(_creds(expired))
    assert exc.value.status_code == 401
