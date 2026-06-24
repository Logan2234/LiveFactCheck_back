"""Tests for the shared text normalization (verification cache + claim dedup)."""

from app.services.normalize import normalize


def test_lowercases_and_trims() -> None:
    assert normalize("  La Tour Eiffel  ") == "la tour eiffel"


def test_collapses_internal_whitespace() -> None:
    assert normalize("Paris\t est   en\nFrance") == "paris est en france"


def test_strips_trailing_punctuation() -> None:
    assert normalize("Paris est en France.") == normalize("paris est en france")
    assert normalize("Vraiment ?!") == "vraiment"


def test_distinct_numbers_stay_distinct() -> None:
    # Equality-only, never fuzzy: close-but-different facts must not collide.
    assert normalize("Le chômage est à 4 %") != normalize("Le chômage est à 14 %")
