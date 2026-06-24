"""Tests that lock the shape of the Anthropic call in claim_extractor.

These guard the prompt-mechanics fixes: deterministic tool schema, cache breakpoint
on the system block (not the tool), and a forced tool_choice on the fast path so the
single offered tool is always called (no silent plain-text drop).
"""

import asyncio

from app.services import claim_extractor
from app.services.claim_extractor import (
    CLAIM_TOOL,
    MAX_TOKENS,
    VALID_STATUSES,
    extract_and_verify,
)


class _Block:
    def __init__(self, type: str, name: str = "", input: dict | None = None) -> None:
        self.type = type
        self.name = name
        self.input = input or {}


class _FakeUsage:
    input_tokens = 1
    output_tokens = 1
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _FakeResponse:
    def __init__(self) -> None:
        self.content = [_Block("tool_use", "submit_claims", {"claims": []})]
        self.usage = _FakeUsage()
        self.stop_reason = "tool_use"


def _capture_create(monkeypatch) -> list[dict]:
    """Record the kwargs of each messages.create call."""
    calls: list[dict] = []

    async def fake_create(*_args, **kwargs):
        calls.append(kwargs)
        return _FakeResponse()

    monkeypatch.setattr(claim_extractor._client.messages, "create", fake_create)
    monkeypatch.setattr(claim_extractor.settings, "VERIFICATION_CACHE_SIZE", 0)
    return calls


def test_fast_path_forces_submit_claims(monkeypatch) -> None:
    calls = _capture_create(monkeypatch)
    asyncio.run(extract_and_verify("trois mots ici", web_search=False))
    assert calls[0]["tool_choice"] == {"type": "tool", "name": "submit_claims"}
    assert calls[0]["max_tokens"] == MAX_TOKENS


def test_thorough_path_keeps_auto(monkeypatch) -> None:
    calls = _capture_create(monkeypatch)
    asyncio.run(extract_and_verify("trois mots ici", web_search=True))
    assert calls[0]["tool_choice"] == {"type": "auto"}


def test_cache_breakpoint_is_on_system_not_tool(monkeypatch) -> None:
    calls = _capture_create(monkeypatch)
    asyncio.run(extract_and_verify("trois mots ici", web_search=False))
    system = calls[0]["system"]
    # System is a list of text blocks carrying the cache_control breakpoint…
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # …and the tool no longer carries one (render order would cache only the tools).
    assert "cache_control" not in CLAIM_TOOL


def test_status_enum_is_deterministic() -> None:
    status_schema = CLAIM_TOOL["input_schema"]["properties"]["claims"]["items"][
        "properties"
    ]["status"]
    assert status_schema["enum"] == sorted(VALID_STATUSES)
