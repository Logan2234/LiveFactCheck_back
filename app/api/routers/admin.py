"""Admin observability & runtime config (all gated by ``require_admin``).

These routes expose diagnostics for the local admin panel: process health,
captured logs, live WS sessions, the active prompt/tool definitions, runtime
config, an ad-hoc Whisper transcription probe and a model-test path.
"""

import asyncio
import logging
import sys

import psutil
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.config import settings
from app.core.observability import get_logs, uptime_seconds
from app.dependencies import require_admin
from app.schemas.admin import (
    AdminHealthResponse,
    AnthropicInfo,
    ConfigEditable,
    ConfigOptions,
    ConfigPatch,
    ConfigPatchResponse,
    ConfigReadonly,
    ConfigResponse,
    HealthConfig,
    LogEntry,
    LogsResponse,
    MemoryInfo,
    PromptResponse,
    WhisperInfo,
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

_EDITABLE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-8",
]
_VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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
        whisper=WhisperInfo(
            model=settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            loaded=is_model_loaded(),
        ),
        anthropic=AnthropicInfo(
            model=settings.ANTHROPIC_MODEL,
            api_key_set=bool(settings.ANTHROPIC_API_KEY),
            api_key_hint=f"...{settings.ANTHROPIC_API_KEY[-4:]}"
            if settings.ANTHROPIC_API_KEY
            else "",
        ),
        config=HealthConfig(
            log_level=settings.LOG_LEVEL,
            jwt_expire_hours=settings.JWT_EXPIRE_HOURS,
            max_claims_per_chunk=settings.MAX_CLAIMS_PER_CHUNK,
        ),
        python_version=sys.version.split()[0],
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


@router.get("/config", response_model=ConfigResponse)
async def admin_config() -> ConfigResponse:
    return ConfigResponse(
        editable=ConfigEditable(
            anthropic_model=settings.ANTHROPIC_MODEL,
            log_level=settings.LOG_LEVEL,
        ),
        readonly=ConfigReadonly(
            whisper_model=settings.WHISPER_MODEL,
            whisper_device=settings.WHISPER_DEVICE,
            jwt_expire_hours=settings.JWT_EXPIRE_HOURS,
            max_claims_per_chunk=settings.MAX_CLAIMS_PER_CHUNK,
        ),
        options=ConfigOptions(
            models=_EDITABLE_MODELS,
            log_levels=_VALID_LOG_LEVELS,
        ),
        note="Les modifications sont perdues au redémarrage (--reload actif).",
    )


@router.patch("/config", response_model=ConfigPatchResponse)
async def patch_config(patch: ConfigPatch) -> ConfigPatchResponse:
    changed: dict[str, str] = {}
    if patch.anthropic_model is not None:
        if patch.anthropic_model not in _EDITABLE_MODELS:
            raise HTTPException(
                status_code=422,
                detail=f"Modèle inconnu : {patch.anthropic_model}",
            )
        settings.ANTHROPIC_MODEL = patch.anthropic_model
        changed["anthropic_model"] = patch.anthropic_model
    if patch.log_level is not None:
        lvl = patch.log_level.upper()
        if lvl not in _VALID_LOG_LEVELS:
            raise HTTPException(
                status_code=422, detail=f"Niveau inconnu : {patch.log_level}"
            )
        settings.LOG_LEVEL = lvl
        logging.getLogger("app").setLevel(lvl)
        changed["log_level"] = lvl
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
    # Diagnostic probe: the result shape varies (segments vs. an error key),
    # so it's returned as a plain dict rather than a fixed response_model.
    return await asyncio.to_thread(transcribe_with_detail, audio_bytes)


@router.post("/model-test", response_model=ModelTestResponse)
async def admin_model_test(req: ModelTestRequest) -> ModelTestResponse:
    result = await debug_extract(req.text, web_search=req.web_search)
    return ModelTestResponse(**result)
