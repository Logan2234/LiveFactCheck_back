"""Tests for transcribe_samples, with the Whisper model mocked.

No real audio or model: we patch ``_get_model`` so the test stays offline and
fast, and assert on what gets passed to ``.transcribe`` and what comes back.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
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


def test_always_auto_detects_and_reports(mock_model: MagicMock) -> None:
    audio = np.zeros(16000, dtype=np.float32)
    text, lang, prob = transcription.transcribe_samples(audio)

    # Transcription always runs in auto mode (language=None) so a mismatched
    # utterance is never translated; the detected language is surfaced for filtering.
    assert mock_model.transcribe.call_args.kwargs["language"] is None
    # The decoded waveform is forwarded as-is (no ffmpeg decode on the live path).
    assert mock_model.transcribe.call_args.args[0] is audio
    assert text == "Hello world."
    assert lang == "en"
    assert prob == 0.987


def test_error_returns_empty_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    model = MagicMock()
    model.transcribe.side_effect = RuntimeError("boom")
    monkeypatch.setattr(transcription, "_get_model", lambda: model)

    audio = np.zeros(16000, dtype=np.float32)
    assert transcription.transcribe_samples(audio) == ("", "", 0.0)
