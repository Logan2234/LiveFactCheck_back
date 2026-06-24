import importlib.util
import io
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

from app.config import settings

logger = logging.getLogger(__name__)

_model = None


def _expose_cuda_libs() -> None:
    """Make the pip-installed NVIDIA CUDA DLLs loadable on Windows.

    The ``nvidia-cublas-cu12`` / ``nvidia-cudnn-cu12`` wheels drop their DLLs
    under ``site-packages/nvidia/*/bin``, which Windows doesn't search by
    default. ctranslate2's CUDA backend needs cuBLAS/cuDNN at inference time, so
    register those dirs before the model loads. No-op off Windows (Linux wheels
    expose their libs via RPATH) and when the ``nvidia`` namespace isn't present.
    """
    if sys.platform != "win32":
        return
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return
    nvidia_root = Path(next(iter(spec.submodule_search_locations)))
    for bin_dir in nvidia_root.glob("*/bin"):
        if bin_dir.is_dir():
            os.add_dll_directory(str(bin_dir))


def preload_model() -> None:
    if settings.AUTO_START_WHISPER:
        _get_model()


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        if settings.WHISPER_DEVICE == "cuda":
            _expose_cuda_libs()

        logger.info(
            "Loading Whisper model '%s' on %s...",
            settings.WHISPER_MODEL,
            settings.WHISPER_DEVICE,
        )

        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type="int8" if settings.WHISPER_DEVICE == "cpu" else "float16",
        )

        logger.info("Whisper model loaded.")
    return _model


def is_model_loaded() -> bool:
    return _model is not None


def transcribe_with_detail(audio: bytes) -> dict:
    """Transcribe encoded audio bytes (ffmpeg-decoded), returning segments + timing.

    Used by the /admin upload probe, which accepts arbitrary files — so unlike the
    live ``transcribe_samples`` path it still decodes via ffmpeg.
    """
    model = _get_model()
    source = io.BytesIO(audio)
    t0 = time.time()
    try:
        segments_gen, info = model.transcribe(
            source,
            language="fr",
            vad_filter=True,
        )
        segments = list(segments_gen)
        elapsed_ms = round((time.time() - t0) * 1000)
        return {
            "text": "".join(s.text for s in segments).strip(),
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration_s": round(info.duration, 2) if info.duration else None,
            "elapsed_ms": elapsed_ms,
            "segments": [
                {
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "text": s.text.strip(),
                    "avg_logprob": round(s.avg_logprob, 3),
                    "no_speech_prob": round(s.no_speech_prob, 3),
                }
                for s in segments
            ],
        }
    except Exception as e:
        logger.error("Whisper detail transcription error: %s", e)
        return {"error": str(e), "text": "", "segments": []}


def transcribe_samples(audio: np.ndarray) -> tuple[str, str, float]:
    """Transcribe an endpointed utterance (float32 PCM @ 16 kHz) into plain text.

    Accepts the decoded waveform directly — the live /ws path streams raw PCM and
    cuts utterances server-side (see services.audio_endpointer), so no ffmpeg decode
    is needed here. Synchronous and CPU-bound — call it from a thread pool.

    Always auto-detects the language: forcing a non-matching language makes
    Whisper translate/hallucinate into that language rather than transcribe
    phonetically (there's no "transcribe verbatim" knob). The detected language
    is returned so the caller can filter on it instead.

    Returns ``(text, detected_language, detected_probability)``; on error the
    text is empty and the language fields are ``("", 0.0)``.
    """
    try:
        segments, info = _get_model().transcribe(
            audio,
            language=None,
            vad_filter=True,
        )
        text = "".join(seg.text for seg in segments).strip()
        return text, info.language, round(info.language_probability, 3)
    except Exception as e:
        logger.error("Whisper transcription error: %s", e)
        return "", "", 0.0
