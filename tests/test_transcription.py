"""Tests for transcribe_chunk language handling, with the Whisper model mocked.

No real audio or model: we patch ``_get_model`` so the test stays offline and
fast, and assert on what gets passed to ``.transcribe`` and what comes back.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import transcription


@pytest.fixture
def mock_model(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch _get_model to return a model whose .transcribe is controllable."""
    model = MagicMock()
    segments = [SimpleNamespace(text="Hello "), SimpleNamespace(text="world.")]
    info = SimpleNamespace(language="en", language_probability=0.987)
    model.transcribe.return_value = (iter(segments), info)
    monkeypatch.setattr(transcription, "_get_model", lambda: model)
    return model


def test_forced_language_is_passed_and_not_reported(mock_model: MagicMock) -> None:
    text, lang, prob = transcription.transcribe_chunk(b"audio", language="en")

    # The forced language reaches WhisperModel.transcribe...
    assert mock_model.transcribe.call_args.kwargs["language"] == "en"
    assert text == "Hello world."
    # ...and the detected fields stay empty (nothing to report when forced).
    assert lang is None
    assert prob is None


def test_auto_mode_detects_and_reports(mock_model: MagicMock) -> None:
    text, lang, prob = transcription.transcribe_chunk(b"audio", language=None)

    # None means auto-detect: Whisper gets language=None and we surface its guess.
    assert mock_model.transcribe.call_args.kwargs["language"] is None
    assert text == "Hello world."
    assert lang == "en"
    assert prob == 0.987


def test_default_is_auto(mock_model: MagicMock) -> None:
    _, lang, _ = transcription.transcribe_chunk(b"audio")
    assert mock_model.transcribe.call_args.kwargs["language"] is None
    assert lang == "en"


def test_error_returns_empty_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    model = MagicMock()
    model.transcribe.side_effect = RuntimeError("boom")
    monkeypatch.setattr(transcription, "_get_model", lambda: model)

    assert transcription.transcribe_chunk(b"audio") == ("", None, None)
