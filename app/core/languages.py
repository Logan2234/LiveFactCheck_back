"""Whisper transcription language codes — the validation source of truth.

faster-whisper ships the canonical set of supported ISO codes in its tokenizer.
We expose it here so the WebSocket config schema can validate a requested
language without re-deriving the list. The frontend mirrors these codes.
"""

from faster_whisper.tokenizer import _LANGUAGE_CODES

# Sentinel meaning "let Whisper auto-detect the language per chunk". Kept distinct
# from a real ISO code so callers can branch on it explicitly.
AUTO_LANGUAGE = "auto"

# Frozen copy so callers can't mutate faster-whisper's internal set.
SUPPORTED_LANGUAGE_CODES: frozenset[str] = frozenset(_LANGUAGE_CODES)


def normalize_language(language: str | None) -> str | None:
    """Map a requested language to a value for ``WhisperModel.transcribe``.

    Returns ``None`` for auto-detection (the ``"auto"`` sentinel, an empty value,
    or an unknown code), and the code itself when it is a supported ISO language.
    Unknown codes fall back to auto rather than raising — a bad client value
    shouldn't break a live session.
    """
    if not language or language == AUTO_LANGUAGE:
        return None
    if language in SUPPORTED_LANGUAGE_CODES:
        return language
    return None
