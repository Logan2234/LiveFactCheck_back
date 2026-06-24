"""Request/response schemas for the /admin/* observability and config routes.

These mirror the JSON the admin panel (front-side ``authFetch``) consumes.
Several payloads are intentionally loose (``dict``) where the shape is
diagnostic-only and not part of a stable contract.
"""

from typing import Any, Literal

from pydantic import BaseModel


class MemoryInfo(BaseModel):
    rss_mb: float
    vms_mb: float


class AdminHealthResponse(BaseModel):
    """Pure runtime health — static config lives in the descriptor (/admin/config)."""

    uptime_seconds: int
    python_version: str
    whisper_loaded: bool
    memory: MemoryInfo | None = None


class PromptResponse(BaseModel):
    system_prompt: str
    claim_tool: dict[str, Any]
    web_search_tool: dict[str, Any]
    valid_statuses: list[str]
    min_words: int
    model: str


FieldKind = Literal["readonly", "editable", "secret_status"]
ValueType = Literal["str", "int", "float", "bool", "list"]


class ConfigFieldValue(BaseModel):
    """One config field rendered on the System page, driven by the descriptor."""

    key: str
    label: str
    kind: FieldKind
    value: Any | None = None  # None for secret_status (raw value never serialised)
    configured: bool | None = None  # set only for secret_status
    options: list[str] | None = None  # closed choice for an editable enum
    value_type: ValueType | None = None  # drives the editable control on the front


class ConfigBlockOut(BaseModel):
    id: str
    title: str
    fields: list[ConfigFieldValue]


class ConfigResponse(BaseModel):
    blocks: list[ConfigBlockOut]
    note: str


class ConfigPatch(BaseModel):
    updates: dict[str, Any]  # {settings key: new value}, editable fields only


class ConfigPatchResponse(BaseModel):
    changed: dict[str, Any]


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
