"""Tests for the WebSocket config-frame parsing in session.py."""

import pytest

from app.core.languages import normalize_language
from app.schemas.claim import VerificationLevel
from app.services.session import parse_config


def test_forced_language_is_normalized() -> None:
    cfg = parse_config('{"type": "config", "language": "en"}')
    assert normalize_language(cfg.language) == "en"


def test_auto_maps_to_none() -> None:
    cfg = parse_config('{"type": "config", "language": "auto"}')
    assert normalize_language(cfg.language) is None


def test_unknown_language_falls_back_to_auto() -> None:
    cfg = parse_config('{"type": "config", "language": "klingon"}')
    assert normalize_language(cfg.language) is None


def test_verification_level_defaults_to_thorough() -> None:
    cfg = parse_config('{"type": "config", "language": "auto"}')
    assert cfg.verification_level == VerificationLevel.THOROUGH


def test_fast_verification_level_is_parsed() -> None:
    cfg = parse_config(
        '{"type": "config", "language": "auto", "verification_level": "fast"}'
    )
    assert cfg.verification_level == VerificationLevel.FAST


def test_invalid_verification_level_raises() -> None:
    with pytest.raises(ValueError):
        parse_config(
            '{"type": "config", "language": "auto", "verification_level": "turbo"}'
        )


def test_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_config("not json")


def test_wrong_type_raises() -> None:
    with pytest.raises(ValueError):
        parse_config('{"type": "transcript", "text": "hi"}')


def test_missing_language_raises() -> None:
    with pytest.raises(ValueError):
        parse_config('{"type": "config"}')
