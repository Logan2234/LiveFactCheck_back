"""Integration tests for the user account routes + admin/user token separation.

Signup/login/me hit a seeded in-memory SQLite via a ``get_db`` override (restored after
each test so it doesn't leak to other modules). Token cross-rejection is tested directly
on the dependencies, avoiding any global override juggling.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routers.users import _login_limiter
from app.core.security import create_token, create_user_token
from app.db.base import Base
from app.db.session import get_db
from app.dependencies import require_admin, require_user
from app.main import app
from app.models import User

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # one shared connection so the in-memory DB persists
)
_TestSession = sessionmaker(bind=_engine, expire_on_commit=False)
Base.metadata.create_all(_engine)

client = TestClient(app)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _use_test_db():
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    with _TestSession() as db:
        db.query(User).delete()
        db.commit()
    _login_limiter._attempts.clear()
    yield
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def _signup(email="alice@example.com", username="alice", password="password123"):
    return client.post(
        "/v1/users/signup",
        json={"email": email, "username": username, "password": password},
    )


def _login(identifier="alice", password="password123"):
    return client.post(
        "/v1/users/login", json={"identifier": identifier, "password": password}
    )


def test_signup_returns_user_without_secrets() -> None:
    resp = _signup()
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert body["username"] == "alice"
    assert "password" not in body
    assert "password_hash" not in body


def test_signup_rejects_duplicate_email() -> None:
    _signup()
    assert _signup(username="bob").status_code == 409


def test_signup_rejects_duplicate_username() -> None:
    _signup()
    assert _signup(email="other@example.com").status_code == 409


def test_login_accepts_email_or_username() -> None:
    _signup()
    for identifier in ("alice@example.com", "alice"):
        resp = _login(identifier=identifier)
        assert resp.status_code == 200
        assert resp.json()["token"]


def test_login_rejects_wrong_password() -> None:
    _signup()
    assert _login(password="nope").status_code == 401


def test_me_returns_current_user() -> None:
    _signup()
    token = _login().json()["token"]
    resp = client.get("/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_me_requires_a_token() -> None:
    assert client.get("/v1/users/me").status_code == 401


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_admin_token_rejected_by_require_user() -> None:
    with pytest.raises(HTTPException) as exc:
        require_user(_creds(create_token()))
    assert exc.value.status_code == 401


def test_user_token_rejected_by_require_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        require_admin(_creds(create_user_token("some-user-id")))
    assert exc.value.status_code == 401
