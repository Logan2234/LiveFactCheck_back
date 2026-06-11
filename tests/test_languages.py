"""Tests for transcription language normalization."""

from app.core.languages import AUTO_LANGUAGE, normalize_language


def test_auto_sentinel_maps_to_none() -> None:
    assert normalize_language(AUTO_LANGUAGE) is None


def test_empty_or_missing_maps_to_none() -> None:
    assert normalize_language("") is None
    assert normalize_language(None) is None


def test_known_code_passes_through() -> None:
    assert normalize_language("fr") == "fr"
    assert normalize_language("en") == "en"


def test_unknown_code_falls_back_to_auto() -> None:
    assert normalize_language("klingon") is None
