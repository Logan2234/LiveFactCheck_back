import io
import logging
import time

from faster_whisper import WhisperModel

from app.config import settings

logger = logging.getLogger(__name__)

_model = None


def preload_model() -> None:
    _get_model()


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        logger.info(
            "Loading Whisper model '%s' on %s...",
            settings.WHISPER_MODEL,
            settings.WHISPER_DEVICE,
        )

        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type="int8"
            if settings.WHISPER_DEVICE == "cpu"
            else "float16",
        )

        logger.info("Whisper model loaded.")
    return _model


def is_model_loaded() -> bool:
    return _model is not None


def transcribe_with_detail(audio: bytes) -> dict:
    """Like transcribe_chunk but returns segments, language info and timing."""
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


def transcribe_chunk(audio: bytes) -> str:
    """Transcribe a self-contained audio chunk into plain text.

    Accepts either raw encoded audio bytes (e.g. a complete WebM/Opus blob,
    decoded via ffmpeg) or a float32 PCM array. Synchronous and CPU-bound —
    call it from a thread pool.
    """
    model = _get_model()
    # faster-whisper accepts a path, a file-like object, or a float32 ndarray.
    # Encoded bytes (a WebM/Opus blob) must be wrapped so ffmpeg can decode them.
    source = io.BytesIO(audio) if isinstance(audio, bytes) else audio
    try:
        segments, _ = model.transcribe(
            source,
            language="fr",
            vad_filter=True,
        )
        return "".join(seg.text for seg in segments).strip()
    except Exception as e:
        logger.error("Whisper transcription error: %s", e)
        return ""
