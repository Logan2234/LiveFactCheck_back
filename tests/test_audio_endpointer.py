"""Tests for the VAD endpointing policy, with a fake VAD (no Silero/ONNX).

The flush logic is plain array arithmetic, so we inject a deterministic ``vad_fn``
that marks every contiguous run of non-zero samples as speech. ``1.0`` = speech,
``0.0`` = silence. Durations are kept tiny so the arrays stay small.
"""

import numpy as np

from app.services.audio_endpointer import SAMPLE_RATE, Endpointer


def _nonzero_vad(audio: np.ndarray) -> list[dict]:
    """Mark each contiguous run of non-zero samples as a speech span."""
    spans: list[dict] = []
    start: int | None = None
    for i, v in enumerate(audio):
        if v != 0 and start is None:
            start = i
        elif v == 0 and start is not None:
            spans.append({"start": start, "end": i})
            start = None
    if start is not None:
        spans.append({"start": start, "end": len(audio)})
    return spans


def _ms(ms: int) -> int:
    return int(ms / 1000 * SAMPLE_RATE)


def _speech(ms: int) -> np.ndarray:
    return np.ones(_ms(ms), dtype=np.float32)


def _silence(ms: int) -> np.ndarray:
    return np.zeros(_ms(ms), dtype=np.float32)


def _endpointer(
    *,
    silence_flush_ms: int = 100,
    max_segment_ms: int = 10_000,
    min_segment_ms: int = 20,
) -> Endpointer:
    return Endpointer(
        silence_flush_ms=silence_flush_ms,
        max_segment_ms=max_segment_ms,
        min_segment_ms=min_segment_ms,
        vad_fn=_nonzero_vad,
    )


def test_flushes_after_trailing_silence() -> None:
    ep = _endpointer(silence_flush_ms=100)
    ep.add(np.concatenate((_speech(500), _silence(150))))

    segment = ep.pop()
    assert segment is not None
    assert segment.size == _ms(500)  # only the speech, trailing silence trimmed
    assert ep.pop() is None  # nothing left but silence


def test_no_flush_until_silence_long_enough() -> None:
    ep = _endpointer(silence_flush_ms=100)
    ep.add(np.concatenate((_speech(500), _silence(50))))  # 50 ms < 100 ms
    assert ep.pop() is None


def test_force_flush_on_max_length_without_pause() -> None:
    ep = _endpointer(silence_flush_ms=100, max_segment_ms=200)
    ep.add(_speech(250))  # pure speech, no pause, over the 200 ms cap

    segment = ep.pop()
    assert segment is not None
    assert segment.size == _ms(250)


def test_too_short_utterance_is_dropped() -> None:
    ep = _endpointer(silence_flush_ms=100, min_segment_ms=500)
    ep.add(np.concatenate((_speech(100), _silence(150))))  # speech < 500 ms

    assert ep.pop() is None  # dropped
    assert ep.pop() is None  # and the buffer was trimmed past it


def test_merges_speech_across_short_gap() -> None:
    ep = _endpointer(silence_flush_ms=100)
    ep.add(
        np.concatenate(
            (_speech(200), _silence(50), _speech(200), _silence(150))
        )  # 50 ms gap stays inside one utterance; 150 ms gap ends it
    )

    segment = ep.pop()
    assert segment is not None
    # From first speech start to last speech end, inner gap included.
    assert segment.size == _ms(200) + _ms(50) + _ms(200)


def test_pure_silence_buffer_is_bounded() -> None:
    ep = _endpointer(max_segment_ms=200)
    ep.add(_silence(300))  # over the cap, no speech

    assert ep.pop() is None
    assert ep._buf.size == 0  # silence was discarded, not kept growing
