"""Static description of the config blocks shown on the admin System page.

Single source of truth for the ``/admin/config`` contract: thematic blocks → fields,
each field carrying its ``kind`` (read-only / editable / secret-status) and, for an
editable enum, the closed list of allowed ``options``. ``key`` is the *exact* name of
a ``Settings`` attribute; the route reads live values by that key and the front renders
the blocks generically.

A completeness test (``tests/test_config_descriptor.py``) asserts the described keys
equal ``set(Settings.model_fields)`` — so adding, renaming or removing a Settings field
turns it red until this descriptor is updated. Fail-closed, by design.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

FieldKind = Literal["readonly", "editable", "secret_status"]


@dataclass(frozen=True)
class ConfigField:
    key: str  # exact Settings attribute name
    label: str
    kind: FieldKind
    options: tuple[str, ...] | None = None  # closed choice for an editable enum


@dataclass(frozen=True)
class ConfigBlock:
    id: str
    title: str
    fields: tuple[ConfigField, ...]


_ANTHROPIC_MODELS = (
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-8",
)

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


BLOCKS: tuple[ConfigBlock, ...] = (
    ConfigBlock(
        id="anthropic",
        title="API Anthropic",
        fields=(
            ConfigField("ANTHROPIC_API_KEY", "Clé API", "secret_status"),
            ConfigField("ANTHROPIC_MODEL", "Modèle", "editable", _ANTHROPIC_MODELS),
        ),
    ),
    ConfigBlock(
        id="whisper",
        title="Whisper",
        fields=(
            ConfigField("WHISPER_MODEL", "Modèle", "readonly"),
            ConfigField("WHISPER_DEVICE", "Device", "readonly"),
            ConfigField("AUTO_START_WHISPER", "Démarrage automatique", "readonly"),
        ),
    ),
    ConfigBlock(
        id="audio",
        title="Audio",
        fields=(
            ConfigField(
                "MAX_AUDIO_BYTES", "Taille max d'une frame (octets)", "editable"
            ),
        ),
    ),
    ConfigBlock(
        id="vad",
        title="Découpage VAD (live)",
        fields=(
            ConfigField(
                "VAD_THRESHOLD", "Seuil de détection de parole (0-1)", "editable"
            ),
            ConfigField(
                "VAD_SILENCE_FLUSH_MS", "Silence de fin d'énoncé (ms)", "editable"
            ),
            ConfigField(
                "VAD_MAX_SEGMENT_MS", "Longueur max d'un énoncé (ms)", "editable"
            ),
            ConfigField(
                "VAD_MIN_SEGMENT_MS", "Longueur min d'un énoncé (ms)", "editable"
            ),
        ),
    ),
    ConfigBlock(
        id="auth",
        title="Auth & Sécurité",
        fields=(
            ConfigField("ADMIN_PASSWORD", "Mot de passe admin", "secret_status"),
            ConfigField("JWT_SECRET", "Secret JWT", "secret_status"),
            ConfigField("JWT_EXPIRE_HOURS", "Expiration JWT (h)", "readonly"),
            ConfigField(
                "LOGIN_RATE_LIMIT_ATTEMPTS", "Tentatives login max", "readonly"
            ),
            ConfigField(
                "LOGIN_RATE_LIMIT_WINDOW_SECONDS", "Fenêtre login (s)", "readonly"
            ),
        ),
    ),
    ConfigBlock(
        id="cors",
        title="CORS",
        fields=(ConfigField("ALLOWED_ORIGINS", "Origines autorisées", "readonly"),),
    ),
    ConfigBlock(
        id="extraction",
        title="Extraction & vérification",
        fields=(
            ConfigField(
                "CONTEXT_TURNS",
                "Fenêtre de contexte (énoncés précédents)",
                "editable",
            ),
        ),
    ),
    ConfigBlock(
        id="persistence",
        title="Persistance des sessions",
        # Read-only: both take effect at startup (the DB engine is built once), so
        # a runtime change wouldn't apply to the live process.
        fields=(
            ConfigField("PERSIST_SESSIONS", "Persistance activée", "readonly"),
            ConfigField("DATABASE_URL", "URL base de données", "readonly"),
        ),
    ),
    ConfigBlock(
        id="logs",
        title="Logs",
        fields=(ConfigField("LOG_LEVEL", "Niveau de log", "editable", _LOG_LEVELS),),
    ),
)


def all_fields() -> Iterator[ConfigField]:
    for block in BLOCKS:
        yield from block.fields


def field_by_key(key: str) -> ConfigField | None:
    return next((f for f in all_fields() if f.key == key), None)


# Every key described above. Cross-checked against Settings.model_fields by the test.
DESCRIBED_KEYS = frozenset(f.key for f in all_fields())

# Secret-status fields: described (so the page shows "configured"/"missing") but their
# raw value must never be serialised. Used by the serialiser and asserted by the tests.
SECRET_KEYS = frozenset(f.key for f in all_fields() if f.kind == "secret_status")
