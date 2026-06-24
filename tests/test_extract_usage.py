"""Tests for the usage/metrics plumbing in extract_and_verify (mocked client).

These lock the behaviour the persistence layer depends on: accumulated token
usage, the API-call count (including the two-turn fallback) and the web_search
count — without any real Anthropic call.
"""

import asyncio

from app.services import claim_extractor
from app.services.claim_extractor import extract_and_verify


class _FakeUsage:
    def __init__(self, i: int = 0, o: int = 0, cw: int = 0, cr: int = 0) -> None:
        self.input_tokens = i
        self.output_tokens = o
        self.cache_creation_input_tokens = cw
        self.cache_read_input_tokens = cr


class _Block:
    def __init__(self, type: str, name: str = "", input: dict | None = None) -> None:
        self.type = type
        self.name = name
        self.input = input or {}


class _FakeResponse:
    def __init__(self, content: list, usage: _FakeUsage, stop_reason: str) -> None:
        self.content = content
        self.usage = usage
        self.stop_reason = stop_reason


_VALID_CLAIM = {
    "text": "La Tour Eiffel mesure 330 m.",
    "status": "verified",
    "explanation": "ok",
    "sources": [],
    "category": "histoire",
    "confidence": 9,
    "counter_claim": "",
    "web_search_used": False,
}


def _patch_responses(monkeypatch, responses: list[_FakeResponse]) -> None:
    queue = list(responses)

    async def fake_create(*_args, **_kwargs) -> _FakeResponse:
        return queue.pop(0)

    monkeypatch.setattr(claim_extractor._client.messages, "create", fake_create)


def test_happy_path_records_usage_and_one_call(monkeypatch) -> None:
    response = _FakeResponse(
        content=[
            _Block("server_tool_use", "web_search"),
            _Block("tool_use", "submit_claims", {"claims": [_VALID_CLAIM]}),
        ],
        usage=_FakeUsage(i=100, o=50, cw=5, cr=10),
        stop_reason="tool_use",
    )
    _patch_responses(monkeypatch, [response])

    result = asyncio.run(extract_and_verify("trois mots ici", web_search=True))

    assert len(result.claims) == 1
    assert result.api_calls == 1
    assert result.web_search_calls == 1
    assert result.usage == {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_write": 5,
        "cache_read": 10,
    }


def test_two_turn_fallback_sums_usage_and_calls(monkeypatch) -> None:
    first = _FakeResponse(
        content=[_Block("server_tool_use", "web_search")],  # searched, no submit
        usage=_FakeUsage(i=200, o=20, cw=0, cr=0),
        stop_reason="tool_use",
    )
    second = _FakeResponse(
        content=[_Block("tool_use", "submit_claims", {"claims": [_VALID_CLAIM]})],
        usage=_FakeUsage(i=80, o=40, cw=0, cr=5),
        stop_reason="tool_use",
    )
    _patch_responses(monkeypatch, [first, second])

    result = asyncio.run(extract_and_verify("trois mots ici", web_search=True))

    assert result.api_calls == 2
    assert result.web_search_calls == 1  # only the first turn searched
    assert result.usage["input_tokens"] == 280
    assert result.usage["output_tokens"] == 60
    assert result.usage["cache_read"] == 5
    assert len(result.claims) == 1


def test_below_min_words_makes_no_call(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise AssertionError("the API must not be called for a too-short utterance")

    monkeypatch.setattr(claim_extractor._client.messages, "create", _boom)

    result = asyncio.run(extract_and_verify("hi"))

    assert result.claims == []
    assert result.api_calls == 0
    assert result.usage == {}
