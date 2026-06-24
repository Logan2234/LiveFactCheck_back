from typing import Literal

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_assignment=True,
    )

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"

    # Whisper local
    WHISPER_MODEL: str = "medium"
    WHISPER_DEVICE: Literal["cpu", "cuda"] = "cpu"

    # Upper bound on a single received audio frame (bytes), on /ws frames and the
    # /admin/whisper/transcribe upload. A /ws PCM frame (~250 ms of 16 kHz mono
    # Int16) is a few KiB; the cap guards against a malformed/oversized blob
    # saturating memory. Default 10 MiB.
    MAX_AUDIO_BYTES: int = 10 * 1024 * 1024

    # Voice-activity endpointing for the live /ws stream. The client streams raw
    # PCM continuously; the server cuts it into utterances on natural pauses
    # (Silero VAD) instead of fixed client-side chunks. See services/audio_endpointer.
    # VAD_THRESHOLD: Silero speech probability above which a frame counts as speech.
    VAD_THRESHOLD: float = 0.5
    # Trailing silence (ms) that closes an utterance and flushes it for transcription.
    VAD_SILENCE_FLUSH_MS: int = 700
    # Force-flush an utterance once it reaches this length, even without a pause
    # (keeps a long monologue from delaying feedback indefinitely).
    VAD_MAX_SEGMENT_MS: int = 12000
    # Drop a flushed utterance shorter than this (filters out blips/noise).
    VAD_MIN_SEGMENT_MS: int = 400

    LOG_LEVEL: str = "INFO"

    # CORS: origines autorisées pour le front (format JSON dans .env, ex.
    # ALLOWED_ORIGINS=["http://localhost:5173"]).
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]

    # Admin panel auth
    ADMIN_PASSWORD: str = ""
    JWT_SECRET: str = ""
    JWT_EXPIRE_HOURS: int = 12

    # Brute-force protection on /admin/login: max failed attempts per client IP
    # within the rolling window before further attempts are rejected with 429.
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300

    AUTO_START_WHISPER: bool = True

    # How many preceding utterances are handed to claim extraction as read-only
    # context so a sentence that only makes sense after the previous one
    # ("Il en est de même de…") can be resolved instead of dropped as unverifiable.
    CONTEXT_TURNS: int = 4

    # Session persistence. PERSIST_SESSIONS gates *writing* sessions, transcripts
    # and verified claims to the DB; the live WS path is unaffected when off. The
    # tables are always created at startup so the /sessions read routes work
    # regardless. DATABASE_URL is any SQLAlchemy URL (default: a local SQLite file).
    PERSIST_SESSIONS: bool = True
    DATABASE_URL: str = "sqlite:///./livefactchecker.db"

    @field_validator("ANTHROPIC_API_KEY")
    @classmethod
    def api_key_must_be_set(cls, v: str) -> str:
        if not v or v.startswith("sk-ant-..."):
            raise ValueError("ANTHROPIC_API_KEY manquante ou non configurée dans .env")
        return v

    @field_validator("ADMIN_PASSWORD", "JWT_SECRET")
    @classmethod
    def admin_secret_must_be_set(cls, v: str, info: ValidationInfo) -> str:
        # L'admin (/admin/*) est monté inconditionnellement : refuser un
        # démarrage sans secret, comme pour ANTHROPIC_API_KEY.
        if not v:
            raise ValueError(f"{info.field_name} manquant ou non configuré dans .env")
        return v


settings = Settings()
