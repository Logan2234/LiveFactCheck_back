"""Admin observability & runtime config (all gated by ``require_admin``).

These routes expose diagnostics for the local admin panel: process health,
captured logs, live WS sessions, the active prompt/tool definitions, runtime
config, an ad-hoc Whisper transcription probe and a model-test path.
"""

import asyncio
import logging
import sys
from typing import Any

import psutil
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import ValidationError

from app.config import settings
from app.core.config_descriptor import BLOCKS, ConfigField, field_by_key
from app.core.observability import get_logs, uptime_seconds
from app.dependencies import require_admin
from app.schemas.admin import (
    AdminHealthResponse,
    ConfigBlockOut,
    ConfigFieldValue,
    ConfigPatch,
    ConfigPatchResponse,
    ConfigResponse,
    LogEntry,
    LogsResponse,
    MemoryInfo,
    PromptResponse,
    ValueType,
    WsStatusResponse,
)
from app.schemas.fact_check import ModelTestRequest, ModelTestResponse
from app.services.claim_extractor import (
    CLAIM_TOOL,
    MIN_WORDS,
    SYSTEM_PROMPT,
    VALID_STATUSES,
    WEB_SEARCH_TOOL,
    debug_extract,
)
from app.services.session import get_sessions_status
from app.services.transcription import is_model_loaded, transcribe_with_detail

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


def _apply_log_level(value: str) -> None:
    logging.getLogger("app").setLevel(value)


def _value_type(value: object) -> ValueType:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, list):
        return "list"
    return "str"


def _serialize_field(field: ConfigField) -> ConfigFieldValue:
    raw = getattr(settings, field.key)
    if field.kind == "secret_status":
        # Raw secret never leaves the server — only whether it is set.
        return ConfigFieldValue(
            key=field.key, label=field.label, kind=field.kind, configured=bool(raw)
        )

    return ConfigFieldValue(
        key=field.key,
        label=field.label,
        kind=field.kind,
        value=raw,
        options=list(field.options) if field.options else None,
        value_type=_value_type(raw),
    )


@router.get("/health", response_model=AdminHealthResponse)
async def admin_health() -> AdminHealthResponse:
    memory: MemoryInfo | None = None
    try:
        mem = psutil.Process().memory_info()
        memory = MemoryInfo(
            rss_mb=round(mem.rss / 1024 / 1024, 1),
            vms_mb=round(mem.vms / 1024 / 1024, 1),
        )
    except (psutil.Error, OSError):
        pass

    return AdminHealthResponse(
        uptime_seconds=uptime_seconds(),
        python_version=sys.version.split()[0],
        whisper_loaded=is_model_loaded(),
        memory=memory,
    )


@router.get("/prompt", response_model=PromptResponse)
async def admin_prompt() -> PromptResponse:
    return PromptResponse(
        system_prompt=SYSTEM_PROMPT,
        claim_tool=dict(CLAIM_TOOL),
        web_search_tool=dict(WEB_SEARCH_TOOL),
        valid_statuses=list(VALID_STATUSES),
        min_words=MIN_WORDS,
        model=settings.ANTHROPIC_MODEL,
    )


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Configuration actuelle du système",
)
async def admin_config() -> ConfigResponse:
    blocks = [
        ConfigBlockOut(
            id=block.id,
            title=block.title,
            fields=[_serialize_field(f) for f in block.fields],
        )
        for block in BLOCKS
    ]

    return ConfigResponse(
        blocks=blocks,
        note="Les modifications sont perdues au redémarrage (--reload actif).",
    )


# Side effects to run after a successful PATCH, beyond setting the attribute.
_EDITABLE_SIDE_EFFECTS = {"LOG_LEVEL": _apply_log_level}


@router.patch("/config", response_model=ConfigPatchResponse)
async def patch_config(patch: ConfigPatch) -> ConfigPatchResponse:
    changed: dict[str, Any] = {}
    for key, value in patch.updates.items():
        field = field_by_key(key)
        if field is None or field.kind != "editable":
            raise HTTPException(status_code=422, detail=f"Champ non modifiable : {key}")
        if field.options is not None and value not in field.options:
            raise HTTPException(
                status_code=422, detail=f"Valeur invalide pour {key} : {value!r}"
            )
        try:
            # validate_assignment on Settings coerces & validates the new value.
            setattr(settings, key, value)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=f"Valeur invalide pour {key}"
            ) from exc
        side_effect = _EDITABLE_SIDE_EFFECTS.get(key)
        if side_effect is not None:
            side_effect(getattr(settings, key))
        changed[key] = getattr(settings, key)
    return ConfigPatchResponse(changed=changed)


@router.get("/logs", response_model=LogsResponse)
async def admin_logs(after: int = Query(default=0, ge=0)) -> LogsResponse:
    return LogsResponse(entries=[LogEntry(**e) for e in get_logs(after)])


@router.get("/ws/status", response_model=WsStatusResponse)
async def admin_ws_status() -> WsStatusResponse:
    return WsStatusResponse(**get_sessions_status())


@router.post("/whisper/transcribe")
async def admin_whisper_transcribe(file: UploadFile = File(...)) -> dict:
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Fichier vide")
    if len(audio_bytes) > settings.MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux (max {settings.MAX_AUDIO_BYTES} octets)",
        )
    # Diagnostic probe: the result shape varies (segments vs. an error key),
    # so it's returned as a plain dict rather than a fixed response_model.
    return await asyncio.to_thread(transcribe_with_detail, audio_bytes)


@router.post("/model-test", response_model=ModelTestResponse)
async def admin_model_test(req: ModelTestRequest) -> ModelTestResponse:
    result = await debug_extract(req.text, web_search=req.web_search)
    return ModelTestResponse(**result)
