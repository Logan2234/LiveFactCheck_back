from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"

    # Whisper local
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: Literal["cpu", "cuda"] = "cpu"

    MAX_CLAIMS_PER_CHUNK: int = 5

    @field_validator("ANTHROPIC_API_KEY")
    @classmethod
    def api_key_must_be_set(cls, v: str) -> str:
        if not v or v.startswith("sk-ant-..."):
            raise ValueError("ANTHROPIC_API_KEY manquante ou non configurée dans .env")
        return v


settings = Settings()
