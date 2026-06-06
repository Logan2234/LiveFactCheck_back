import asyncio
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

from faster_whisper import WhisperModel

from app.config import settings

_model = None
_executor = ThreadPoolExecutor(max_workers=2)


def preload_model() -> None:
    _get_model()


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        print(
            f"⏳ Loading Whisper model '{settings.WHISPER_MODEL}' on {settings.WHISPER_DEVICE}..."
        )
        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type="int8" if settings.WHISPER_DEVICE == "cpu" else "float16",
        )
        print("✅ Whisper model loaded.")
    return _model


async def transcribe_audio(audio_data: bytes) -> str:
    """Transcribe audio bytes using local Whisper model."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _transcribe_sync, audio_data)


def _transcribe_sync(audio_data: bytes) -> str:
    """Synchronous transcription (runs in thread pool)."""
    model = _get_model()
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            tmp_path = f.name
            f.write(audio_data)
            f.flush()

        segments, info = model.transcribe(tmp_path, language="fr", vad_filter=True)

        text = " ".join(seg.text.strip() for seg in segments)

        if text:
            print(f"Transcribed: '{text}'")

        return text
    except Exception as e:
        print(f"Whisper error: {e}")
        return ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
