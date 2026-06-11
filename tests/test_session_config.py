"""Tests for the WebSocket config-frame parsing in session.py."""

import pytest

from app.services.session import parse_config_language


def test_forced_language_is_normalized() -> None:
    assert parse_config_language('{"type": "config", "language": "en"}') == "en"


def test_auto_maps_to_none() -> None:
    assert parse_config_language('{"type": "config", "language": "auto"}') is None


def test_unknown_language_falls_back_to_auto() -> None:
    assert parse_config_language('{"type": "config", "language": "klingon"}') is None


def test_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_config_language("not json")


def test_wrong_type_raises() -> None:
    with pytest.raises(ValueError):
        parse_config_language('{"type": "transcript", "text": "hi"}')


def test_missing_language_raises() -> None:
    with pytest.raises(ValueError):
        parse_config_language('{"type": "config"}')
