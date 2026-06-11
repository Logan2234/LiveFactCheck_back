import io
import logging
import time

from faster_whisper import WhisperModel

from app.config import settings

logger = logging.getLogger(__name__)

_model = None


def preload_model() -> None:
    if settings.AUTO_START_WHISPER:
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
            compute_type="int8" if settings.WHISPER_DEVICE == "cpu" else "float16",
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


def transcribe_chunk(
    audio: bytes, language: str | None = None
) -> tuple[str, str | None, float | None]:
    """Transcribe a self-contained audio chunk into plain text.

    Accepts raw encoded audio bytes (e.g. a complete WebM/Opus blob,
    decoded via ffmpeg). Synchronous and CPU-bound — call it from a thread pool.

    ``language`` is an ISO code to force a language, or ``None`` to auto-detect.
    Returns ``(text, detected_language, detected_probability)``; the detected
    fields are only populated in auto mode (when ``language is None``) — when a
    language is forced there's nothing to report back.
    """
    try:
        segments, info = _get_model().transcribe(
            io.BytesIO(audio),
            language=language,
            vad_filter=True,
        )

        text = "".join(seg.text for seg in segments).strip()

        if language is None:
            return text, info.language, round(info.language_probability, 3)

        return text, None, None
    except Exception as e:
        logger.error("Whisper transcription error: %s", e)
        return "", None, None
