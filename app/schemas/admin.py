"""Request/response schemas for the /admin/* observability and config routes.

These mirror the JSON the admin panel (front-side ``authFetch``) consumes.
Several payloads are intentionally loose (``dict``) where the shape is
diagnostic-only and not part of a stable contract.
"""

from typing import Any

from pydantic import BaseModel


class WhisperInfo(BaseModel):
    model: str
    device: str
    loaded: bool


class AnthropicInfo(BaseModel):
    model: str
    api_key_set: bool
    api_key_hint: str


class HealthConfig(BaseModel):
    log_level: str
    jwt_expire_hours: int
    max_claims_per_chunk: int


class MemoryInfo(BaseModel):
    rss_mb: float
    vms_mb: float


class AdminHealthResponse(BaseModel):
    uptime_seconds: int
    whisper: WhisperInfo
    anthropic: AnthropicInfo
    config: HealthConfig
    python_version: str
    memory: MemoryInfo | None = None


class PromptResponse(BaseModel):
    system_prompt: str
    claim_tool: dict[str, Any]
    web_search_tool: dict[str, Any]
    valid_statuses: list[str]
    min_words: int
    model: str


class ConfigPatch(BaseModel):
    anthropic_model: str | None = None
    log_level: str | None = None


class ConfigEditable(BaseModel):
    anthropic_model: str
    log_level: str


class ConfigReadonly(BaseModel):
    whisper_model: str
    whisper_device: str
    jwt_expire_hours: int
    max_claims_per_chunk: int


class ConfigOptions(BaseModel):
    models: list[str]
    log_levels: list[str]


class ConfigResponse(BaseModel):
    editable: ConfigEditable
    readonly: ConfigReadonly
    options: ConfigOptions
    note: str


class ConfigPatchResponse(BaseModel):
    changed: dict[str, str]


class LogEntry(BaseModel):
    id: int
    t: float
    level: str
    logger: str
    msg: str


class LogsResponse(BaseModel):
    entries: list[LogEntry]


class WsSessionInfo(BaseModel):
    id: str
    connected_at: float
    client: str
    chunks_received: int
    transcripts: int
    claims_spawned: int
    active_tasks: int
    last_transcript: str
    idle_s: int


class WsStatusResponse(BaseModel):
    active: list[WsSessionInfo]
    total_since_start: int
