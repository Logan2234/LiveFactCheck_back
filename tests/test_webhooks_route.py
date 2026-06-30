"""Integration tests for the per-user webhook routes.

Each user manages only their own webhooks. Tokens are minted directly; the routes only
need the user id from the token, so no User row is required (the in-memory SQLite does
not enforce the FK). A ``get_db`` override points the routes at a seeded test DB and is
restored after each test.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_user_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Webhook

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
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
        db.query(Webhook).delete()
        db.commit()
    yield
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def _auth(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_user_token(user_id)}"}


def _create(headers: dict, **overrides) -> object:
    body = {"name": "My Slack", "url": "https://hooks.example.com/abc"}
    body.update(overrides)
    return client.post("/v1/webhooks", json=body, headers=headers)


def test_create_returns_webhook_with_defaults_and_secret() -> None:
    resp = _create(_auth("user-a"))
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "My Slack"
    assert body["kind"] == "custom"  # default destination type
    assert body["trigger_statuses"] == ["false"]  # default filter
    assert body["enabled"] is True
    assert body["failure_count"] == 0
    assert body["secret"]  # generated server-side


def test_create_accepts_kind() -> None:
    resp = _create(_auth("user-a"), kind="slack")
    assert resp.status_code == 201
    assert resp.json()["kind"] == "slack"


def test_create_rejects_unknown_kind() -> None:
    assert _create(_auth("user-a"), kind="telegram").status_code == 422


def test_create_accepts_custom_trigger_statuses() -> None:
    resp = _create(_auth("user-a"), trigger_statuses=["false", "uncertain"])
    assert resp.status_code == 201
    assert resp.json()["trigger_statuses"] == ["false", "uncertain"]


def test_create_rejects_unknown_status() -> None:
    assert _create(_auth("user-a"), trigger_statuses=["bogus"]).status_code == 422


def test_create_rejects_empty_trigger_statuses() -> None:
    assert _create(_auth("user-a"), trigger_statuses=[]).status_code == 422


def test_create_rejects_invalid_url() -> None:
    assert _create(_auth("user-a"), url="not-a-url").status_code == 422


def test_list_returns_only_callers_webhooks() -> None:
    _create(_auth("user-a"), name="A1")
    _create(_auth("user-b"), name="B1")

    a_webhooks = client.get("/v1/webhooks", headers=_auth("user-a")).json()
    assert [w["name"] for w in a_webhooks] == ["A1"]


def test_delete_own_webhook() -> None:
    created = _create(_auth("user-a")).json()
    resp = client.delete(f"/v1/webhooks/{created['id']}", headers=_auth("user-a"))
    assert resp.status_code == 204
    assert client.get("/v1/webhooks", headers=_auth("user-a")).json() == []


def test_cannot_delete_another_users_webhook() -> None:
    created = _create(_auth("user-a")).json()
    resp = client.delete(f"/v1/webhooks/{created['id']}", headers=_auth("user-b"))
    assert resp.status_code == 404
    # Still there for the owner.
    assert len(client.get("/v1/webhooks", headers=_auth("user-a")).json()) == 1


def test_routes_require_authentication() -> None:
    assert client.get("/v1/webhooks").status_code == 401
    assert client.post("/v1/webhooks", json={}).status_code == 401
