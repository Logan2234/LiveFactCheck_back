"""Tests for the startup validators in ``app.config.Settings``.

Explicit constructor args take precedence over env vars, so we can build a
``Settings`` instance directly without touching the process environment set by
``conftest.py``.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_valid_settings_build() -> None:
    settings = Settings(
        ANTHROPIC_API_KEY="test-key-not-a-placeholder",
        ADMIN_PASSWORD="ok",
        JWT_SECRET="ok",
    )
    
    assert settings.ADMIN_PASSWORD == "ok"
    assert settings.JWT_SECRET == "ok"


@pytest.mark.parametrize(
    ("admin_password", "jwt_secret"),
    [("", "ok"), ("ok", "")],
)
def test_empty_admin_secret_fails_startup(admin_password: str, jwt_secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            ANTHROPIC_API_KEY="test-key-not-a-placeholder",
            ADMIN_PASSWORD=admin_password,
            JWT_SECRET=jwt_secret,
        )
