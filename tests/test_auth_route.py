"""Integration tests for /admin/login, focused on brute-force protection.

The module-level limiter is shared process state, so each test clears it first.
TestClient sends every request from the same client host, which is exactly what
we need to drive the per-IP counter to its limit.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.routers.auth import _login_limiter
from app.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_limiter() -> None:
    _login_limiter._attempts.clear()


def test_correct_password_returns_token() -> None:
    resp = client.post("/admin/login", json={"password": settings.ADMIN_PASSWORD})

    assert resp.status_code == 200
    assert resp.json()["token"]


def test_repeated_failures_get_rate_limited() -> None:
    for _ in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS):
        resp = client.post("/admin/login", json={"password": "wrong"})
        assert resp.status_code == 401

    blocked = client.post("/admin/login", json={"password": "wrong"})
    assert blocked.status_code == 429


def test_block_applies_even_to_correct_password() -> None:
    # Once blocked, the limiter short-circuits before the password is checked.
    for _ in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS):
        client.post("/admin/login", json={"password": "wrong"})

    resp = client.post("/admin/login", json={"password": settings.ADMIN_PASSWORD})
    assert resp.status_code == 429


def test_success_resets_failure_counter() -> None:
    for _ in range(settings.LOGIN_RATE_LIMIT_ATTEMPTS - 1):
        client.post("/admin/login", json={"password": "wrong"})

    ok = client.post("/admin/login", json={"password": settings.ADMIN_PASSWORD})
    assert ok.status_code == 200

    # Counter was reset, so a fresh batch of failures is allowed again.
    resp = client.post("/admin/login", json={"password": "wrong"})
    assert resp.status_code == 401
