"""Tests for the config descriptor and the descriptor-driven /admin/config routes.

The completeness test is the safety net: it pins the descriptor to ``Settings`` so a
field added (or renamed/removed) without updating the descriptor turns this red. The
rest cover the contract the System page relies on — secrets never serialised, generic
editable PATCH with type coercion and rejection of non-editable / invalid values.

``require_admin`` is overridden to run offline (cf. test_audio_size_limit.py).
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.core.config_descriptor import DESCRIBED_KEYS, SECRET_KEYS
from app.dependencies import require_admin
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_admin_auth():
    app.dependency_overrides[require_admin] = lambda: None
    yield
    app.dependency_overrides.pop(require_admin, None)


def test_descriptor_covers_every_settings_field() -> None:
    # `==` (not subset) catches BOTH a new undescribed field AND a stale descriptor key.
    assert set(Settings.model_fields) == DESCRIBED_KEYS


def test_config_endpoint_returns_all_described_fields() -> None:
    resp = client.get("/admin/config")
    assert resp.status_code == 200
    returned = {f["key"] for b in resp.json()["blocks"] for f in b["fields"]}
    assert returned == DESCRIBED_KEYS


def test_secrets_never_serialised() -> None:
    resp = client.get("/admin/config")
    body = resp.text
    fields = {f["key"]: f for b in resp.json()["blocks"] for f in b["fields"]}
    for key in SECRET_KEYS:
        raw = str(getattr(settings, key))
        if raw:
            assert raw not in body  # raw secret value must never appear in the payload
        assert fields[key]["value"] is None
        assert isinstance(fields[key]["configured"], bool)


def test_patch_editable_int_coerces_string() -> None:
    original = settings.MAX_AUDIO_BYTES
    try:
        resp = client.patch(
            "/admin/config", json={"updates": {"MAX_AUDIO_BYTES": "2048"}}
        )
        assert resp.status_code == 200
        assert settings.MAX_AUDIO_BYTES == 2048  # coerced str -> int by Pydantic
    finally:
        settings.MAX_AUDIO_BYTES = original


def test_patch_rejects_non_editable_field() -> None:
    resp = client.patch("/admin/config", json={"updates": {"WHISPER_MODEL": "large"}})
    assert resp.status_code == 422
    assert settings.WHISPER_MODEL != "large"


def test_patch_rejects_value_outside_options() -> None:
    resp = client.patch("/admin/config", json={"updates": {"ANTHROPIC_MODEL": "gpt-4"}})
    assert resp.status_code == 422
    assert settings.ANTHROPIC_MODEL != "gpt-4"


def test_patch_rejects_uncoercible_value() -> None:
    original = settings.MAX_AUDIO_BYTES
    try:
        resp = client.patch(
            "/admin/config", json={"updates": {"MAX_AUDIO_BYTES": "not-an-int"}}
        )
        assert resp.status_code == 422
        assert original == settings.MAX_AUDIO_BYTES
    finally:
        settings.MAX_AUDIO_BYTES = original


def test_patch_log_level_applies_side_effect() -> None:
    original = settings.LOG_LEVEL
    try:
        resp = client.patch("/admin/config", json={"updates": {"LOG_LEVEL": "DEBUG"}})
        assert resp.status_code == 200
        assert settings.LOG_LEVEL == "DEBUG"
        assert logging.getLogger("app").level == logging.DEBUG
    finally:
        settings.LOG_LEVEL = original
        logging.getLogger("app").setLevel(original)
