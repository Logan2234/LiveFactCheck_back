"""Unit tests for the pure claim-normalisation logic in claim_extractor.

These exercise ``_parse_claims`` (the function that turns raw model tool output
into clean claim dicts) without any network call. The Anthropic round-trip in
``extract_and_verify`` is left for a later integration test with a mocked client.
"""

from app.services.claim_extractor import _build_analysis_prompt, _parse_claims


def test_keeps_valid_claim_and_normalises_fields() -> None:
    raw = [
        {
            "text": "La Tour Eiffel mesure 330 m.",
            "status": "verified",
            "explanation": "Hauteur avec antennes.",
            "sources": ["https://example.com"],
            "category": "histoire",
            "confidence": 9,
            "counter_claim": "",
            "web_search_used": True,
        }
    ]

    [claim] = _parse_claims(raw)

    assert claim["text"] == "La Tour Eiffel mesure 330 m."
    assert claim["status"] == "verified"
    assert claim["confidence"] == 9
    assert claim["web_search_used"] is True


def test_unknown_status_falls_back_to_uncertain() -> None:
    [claim] = _parse_claims([{"text": "x", "status": "definitely-true"}])
    assert claim["status"] == "uncertain"


def test_confidence_is_clamped_to_0_10() -> None:
    claims = _parse_claims(
        [
            {"text": "too high", "status": "verified", "confidence": 42},
            {"text": "too low", "status": "verified", "confidence": -5},
            {"text": "not a number", "status": "verified", "confidence": "huh"},
        ]
    )
    assert [c["confidence"] for c in claims] == [10, 0, 0]


def test_defaults_applied_for_missing_optional_fields() -> None:
    [claim] = _parse_claims([{"text": "minimal", "status": "verified"}])
    assert claim["explanation"] == ""
    assert claim["sources"] == []
    assert claim["category"] == "autre"
    assert claim["counter_claim"] == ""
    assert claim["web_search_used"] is False


def test_entries_without_text_are_dropped() -> None:
    raw = [
        {"status": "verified"},  # no "text" key
        "not a dict",
        {"text": "kept", "status": "verified"},
    ]
    claims = _parse_claims(raw)
    assert [c["text"] for c in claims] == ["kept"]


def test_web_search_used_is_strict_boolean() -> None:
    # Anything that isn't literally True must normalise to False.
    [truthy] = _parse_claims(
        [{"text": "a", "status": "verified", "web_search_used": "yes"}]
    )
    assert truthy["web_search_used"] is False


def test_prompt_without_context_is_the_bare_text() -> None:
    prompt = _build_analysis_prompt("Il en est de même de 1*2", None)
    assert "Il en est de même de 1*2" in prompt
    assert "Contexte précédent" not in prompt


def test_prompt_with_context_includes_preceding_utterances() -> None:
    # Regression: without the preceding "1 + 1 = 2", the model can't resolve the
    # back-reference and drops the second utterance as unverifiable.
    prompt = _build_analysis_prompt(
        "Il en est de même de 1*2", ["1 + 1 = 2.", "Voici un exemple."]
    )
    assert "1 + 1 = 2." in prompt
    assert "Voici un exemple." in prompt
    assert "Il en est de même de 1*2" in prompt
    # The guard that stops the model from re-extracting claims from the context.
    assert "AUCUN claim" in prompt


def test_empty_context_list_is_treated_as_no_context() -> None:
    assert _build_analysis_prompt("x", []) == _build_analysis_prompt("x", None)
