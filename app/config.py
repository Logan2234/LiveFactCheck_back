from typing import Literal

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"

    # Whisper local
    WHISPER_MODEL: str = "medium"
    WHISPER_DEVICE: Literal["cpu", "cuda"] = "cpu"

    MAX_CLAIMS_PER_CHUNK: int = 5

    LOG_LEVEL: str = "INFO"

    # CORS: origines autorisées pour le front (format JSON dans .env, ex.
    # ALLOWED_ORIGINS=["http://localhost:5173"]).
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]

    # Admin panel auth
    ADMIN_PASSWORD: str = ""
    JWT_SECRET: str = ""
    JWT_EXPIRE_HOURS: int = 12

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
