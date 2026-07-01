"""Integration tests for the /admin observability & config routes.

One test per route in ``api/routers/admin.py``, driven through ``TestClient`` with
``require_admin`` overridden (the same pattern ``test_sessions_route`` uses for the
/sessions routes). The two routes that would do real work — Whisper transcription and
the model-test API call — have their service functions mocked, so nothing hits ffmpeg
or the Anthropic API.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.routers import admin
from app.config import settings
from app.dependencies import require_admin
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _override_admin() -> None:
    # Bypass the JWT check per test; another module may pop this, so set it fresh.
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    yield
    app.dependency_overrides.pop(require_admin, None)


def test_routes_require_admin() -> None:
    # Drop the override to confirm the router really is gated.
    app.dependency_overrides.pop(require_admin, None)
    assert client.get("/v1/admin/health").status_code == 401
    assert client.get("/v1/admin/config").status_code == 401


def test_health() -> None:
    resp = client.get("/v1/admin/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "uptime_seconds" in body
    assert body["python_version"]


def test_prompt() -> None:
    resp = client.get("/v1/admin/prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["system_prompt"]
    assert body["min_words"] >= 1
    assert isinstance(body["valid_statuses"], list)


def test_config_lists_blocks() -> None:
    resp = client.get("/v1/admin/config")
    assert resp.status_code == 200
    blocks = resp.json()["blocks"]
    keys = {f["key"] for b in blocks for f in b["fields"]}
    assert "ANTHROPIC_MODEL" in keys
    # A secret-status field reports whether it's set, never its raw value.
    api_key = next(
        f for b in blocks for f in b["fields"] if f["key"] == "ANTHROPIC_API_KEY"
    )
    assert "value" not in api_key or api_key.get("value") is None
    assert "configured" in api_key


def test_patch_config_updates_editable_field() -> None:
    original: str = settings.LOG_LEVEL
    try:
        resp = client.patch(
            "/v1/admin/config", json={"updates": {"LOG_LEVEL": "DEBUG"}}
        )
        assert resp.status_code == 200
        assert resp.json()["changed"] == {"LOG_LEVEL": "DEBUG"}
        assert settings.LOG_LEVEL == "DEBUG"
    finally:
        settings.LOG_LEVEL = original


def test_patch_config_rejects_non_editable_field() -> None:
    resp = client.patch(
        "/v1/admin/config", json={"updates": {"DATABASE_URL": "sqlite://x"}}
    )
    assert resp.status_code == 422


def test_logs() -> None:
    resp = client.get("/v1/admin/logs")
    assert resp.status_code == 200
    assert "entries" in resp.json()


def test_ws_status() -> None:
    resp = client.get("/v1/admin/ws/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] == []
    assert "total_since_start" in body


def test_whisper_transcribe(monkeypatch) -> None:
    monkeypatch.setattr(
        admin, "transcribe_with_detail", lambda audio: {"segments": ["bonjour"]}
    )
    resp = client.post(
        "/v1/admin/whisper/transcribe",
        files={"file": ("clip.wav", b"\x00\x01", "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"segments": ["bonjour"]}


def test_whisper_transcribe_rejects_empty_file() -> None:
    resp = client.post(
        "/v1/admin/whisper/transcribe", files={"file": ("clip.wav", b"", "audio/wav")}
    )
    assert resp.status_code == 422


def test_model_test(monkeypatch) -> None:
    async def _fake_extract(text, web_search):
        return {
            "claims": [],
            "turns": 1,
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "model": "test-model",
            "web_search_enabled": web_search,
            "web_search_called": False,
        }

    monkeypatch.setattr(admin, "debug_extract", _fake_extract)
    monkeypatch.setattr(admin, "estimate_cost", lambda *a, **k: 0.0)

    resp = client.post("/v1/admin/model-test", json={"text": "La Terre est plate."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["turns"] == 1
    assert body["model"] == "test-model"
    assert body["estimated_cost_usd"] == 0.0
