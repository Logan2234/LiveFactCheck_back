"""Server-side utterance endpointing for the live /ws PCM stream.

The client streams raw PCM (16 kHz mono, Int16 frames decoded to float32) with no
fixed chunking. This module buffers the stream and cuts it into utterances on
natural pauses using Silero VAD, replacing the old fixed ~5 s client-side chunks
(which dropped audio at every boundary and split words/sentences).

The endpointing *policy* (when to flush) is plain array logic, decoupled from the
VAD model via an injectable ``vad_fn`` so it can be unit-tested without ONNX.
"""

from collections.abc import Callable

import numpy as np
from faster_whisper.vad import VadOptions, get_speech_timestamps

# The wire contract fixes this: the client always sends 16 kHz mono PCM. It is a
# constant, not a setting — changing it server-side alone would mis-decode audio.
SAMPLE_RATE = 16000

# Padding kept around detected speech when Silero reports spans. Internal detail,
# not exposed as a tunable.
_SPEECH_PAD_MS = 200

# A VAD function: PCM float32 @ 16 kHz -> speech spans as ``{"start", "end"}`` dicts
# in sample indices (the shape faster-whisper's get_speech_timestamps returns).
VadFn = Callable[[np.ndarray], list[dict]]


def silero_vad(threshold: float) -> VadFn:
    """Production VAD: Silero (bundled with faster-whisper, no extra dependency)."""

    options = VadOptions(threshold=threshold, speech_pad_ms=_SPEECH_PAD_MS)

    def run(audio: np.ndarray) -> list[dict]:
        return get_speech_timestamps(audio, options, sampling_rate=SAMPLE_RATE)

    return run


def _ms_to_samples(ms: int) -> int:
    return int(ms / 1000 * SAMPLE_RATE)


class Endpointer:
    """Buffers a PCM stream and yields one utterance at a time on pause/length.

    Feed frames with :meth:`add`, then call :meth:`pop` repeatedly until it returns
    ``None`` to drain every utterance the policy has completed. A single connection
    owns one instance and drives it sequentially, so the buffer needs no locking.
    """

    def __init__(
        self,
        *,
        silence_flush_ms: int,
        max_segment_ms: int,
        min_segment_ms: int,
        vad_fn: VadFn,
    ) -> None:
        self._silence_flush = _ms_to_samples(silence_flush_ms)
        self._max_segment = _ms_to_samples(max_segment_ms)
        self._min_segment = _ms_to_samples(min_segment_ms)
        self._vad_fn = vad_fn
        self._buf = np.empty(0, dtype=np.float32)

    def add(self, samples: np.ndarray) -> None:
        self._buf = np.concatenate((self._buf, samples))

    def pop(self) -> np.ndarray | None:
        """Return the next ready utterance and trim the buffer, or ``None``.

        An utterance is ready when speech is followed by ``silence_flush_ms`` of
        trailing silence, or once the buffer reaches ``max_segment_ms`` (force-flush
        a pauseless monologue). Utterances shorter than ``min_segment_ms`` are
        dropped. Runs the (CPU-bound) VAD, so call it off the event loop.
        """
        if self._buf.size == 0:
            return None

        spans = self._vad_fn(self._buf)
        if not spans:
            # No speech yet: don't let pure silence grow without bound.
            if self._buf.size > self._max_segment:
                self._buf = np.empty(0, dtype=np.float32)
            return None

        first_start = spans[0]["start"]
        last_end = spans[-1]["end"]
        trailing_silence = self._buf.size - last_end

        ended = trailing_silence >= self._silence_flush
        too_long = self._buf.size >= self._max_segment
        if not (ended or too_long):
            return None

        # Cut at the end of the last detected speech: on a normal flush the rest is
        # silence; on a force-flush mid-speech this still avoids slicing past the
        # last known speech sample.
        segment = self._buf[first_start:last_end]
        self._buf = self._buf[last_end:]

        if segment.size < self._min_segment:
            return None
        return segment
