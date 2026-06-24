"""Tests for the process-level verification cache in claim_extractor.

A repeated utterance must reuse its result instead of repaying an Anthropic call,
but only when no web_search was involved (web-sourced facts go stale). The client
is mocked and calls are counted, so no real API call is made.
"""

import asyncio

import pytest

from app.services import claim_extractor
from app.services.claim_extractor import extract_and_verify


class _FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 10
        self.output_tokens = 5
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class _Block:
    def __init__(self, type: str, name: str = "", input: dict | None = None) -> None:
        self.type = type
        self.name = name
        self.input = input or {}


class _FakeResponse:
    def __init__(self, content: list) -> None:
        self.content = content
        self.usage = _FakeUsage()
        self.stop_reason = "tool_use"


_CLAIM = {
    "text": "La Tour Eiffel mesure 330 m.",
    "status": "verified",
    "explanation": "ok",
    "sources": [],
    "category": "histoire",
    "confidence": 9,
    "counter_claim": "",
    "web_search_used": False,
}


def _submit(claims: list[dict]) -> _FakeResponse:
    return _FakeResponse([_Block("tool_use", "submit_claims", {"claims": claims})])


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch) -> None:
    """Each test starts from an empty, enabled cache of known size."""
    claim_extractor._verification_cache.clear()
    monkeypatch.setattr(claim_extractor.settings, "VERIFICATION_CACHE_SIZE", 8)


def _counting_create(monkeypatch, response_factory) -> list[int]:
    calls = [0]

    async def fake_create(*_args, **_kwargs):
        calls[0] += 1
        return response_factory()

    monkeypatch.setattr(claim_extractor._client.messages, "create", fake_create)
    return calls


def test_repeated_utterance_hits_cache(monkeypatch) -> None:
    calls = _counting_create(monkeypatch, lambda: _submit([_CLAIM]))

    first = asyncio.run(extract_and_verify("la tour eiffel mesure", web_search=False))
    second = asyncio.run(extract_and_verify("La Tour Eiffel mesure.", web_search=False))

    assert calls[0] == 1  # second call served from cache (normalized to same key)
    assert first.claims == second.claims
    assert second.api_calls == 0  # nothing was called on the hit
    assert second.usage == {}


def test_web_search_result_is_not_cached(monkeypatch) -> None:
    # A response that used web_search must not be cached: re-asking re-calls the API.
    def _searched() -> _FakeResponse:
        return _FakeResponse(
            [
                _Block("server_tool_use", "web_search"),
                _Block("tool_use", "submit_claims", {"claims": [_CLAIM]}),
            ]
        )

    calls = _counting_create(monkeypatch, _searched)

    asyncio.run(extract_and_verify("un fait d'actualité récent", web_search=True))
    asyncio.run(extract_and_verify("un fait d'actualité récent", web_search=True))

    assert calls[0] == 2  # not cached → called twice


def test_disabled_cache_never_hits(monkeypatch) -> None:
    monkeypatch.setattr(claim_extractor.settings, "VERIFICATION_CACHE_SIZE", 0)
    calls = _counting_create(monkeypatch, lambda: _submit([_CLAIM]))

    asyncio.run(extract_and_verify("la tour eiffel mesure", web_search=False))
    asyncio.run(extract_and_verify("la tour eiffel mesure", web_search=False))

    assert calls[0] == 2


def test_eviction_past_capacity(monkeypatch) -> None:
    monkeypatch.setattr(claim_extractor.settings, "VERIFICATION_CACHE_SIZE", 1)
    calls = _counting_create(monkeypatch, lambda: _submit([_CLAIM]))

    asyncio.run(extract_and_verify("premier énoncé distinct", web_search=False))
    asyncio.run(extract_and_verify("second énoncé distinct", web_search=False))
    # The first key was evicted (size 1), so re-asking it re-calls the API.
    asyncio.run(extract_and_verify("premier énoncé distinct", web_search=False))

    assert calls[0] == 3
