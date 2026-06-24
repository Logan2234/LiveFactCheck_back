"""Presence guards for the safety-critical hardening of the fact-check prompt.

These do NOT verify behaviour (that needs a live API call) — they only ensure the
hardening added after the "Bardella confidently marked verified from a fake source"
incident isn't silently dropped by a later edit to SYSTEM_PROMPT.
"""

from app.services.claim_extractor import SYSTEM_PROMPT


def test_prompt_has_a_false_verdict_example() -> None:
    # The two original examples both showed the speaker being right → "verified",
    # biasing toward confirmation. A "false" example must balance them.
    assert "Ex. faux" in SYSTEM_PROMPT
    assert "status false" in SYSTEM_PROMPT


def test_prompt_warns_against_trusting_a_lone_web_source() -> None:
    # The core failure: a single dubious web result overrode correct internal
    # knowledge. The prompt must tell the model not to renege on solid knowledge.
    assert "Fiabilité des sources" in SYSTEM_PROMPT
    assert "une source web unique ne prouve rien" in SYSTEM_PROMPT


def test_prompt_caps_confidence_on_weak_sourcing() -> None:
    assert "plafonne" in SYSTEM_PROMPT
