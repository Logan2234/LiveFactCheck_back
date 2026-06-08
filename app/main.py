import asyncio
import logging
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from itertools import count

import psutil
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.services.auth import check_password, create_token, require_admin
from app.services.claim_extractor import (
    CLAIM_TOOL,
    MIN_WORDS,
    SYSTEM_PROMPT,
    VALID_STATUSES,
    WEB_SEARCH_TOOL,
    debug_extract,
    extract_and_verify,
)
from app.services.session import get_sessions_status, run_session
from app.services.transcription import (
    is_model_loaded,
    preload_model,
    transcribe_with_detail,
)

_start_time = time.time()
_log_history: deque = deque(maxlen=300)
_log_counter = count(1)


class _LogCaptureHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _log_history.append(
            {
                "id": next(_log_counter),
                "t": record.created,
                "level": record.levelname,
                "logger": record.name,
                "msg": self.format(record),
            }
        )


_capture_handler = _LogCaptureHandler()
_capture_handler.setFormatter(logging.Formatter("%(message)s"))


def _setup_logging() -> None:
    uvicorn_logger = logging.getLogger("uvicorn")
    app_logger = logging.getLogger("app")
    app_logger.handlers = list(uvicorn_logger.handlers)
    app_logger.addHandler(_capture_handler)
    app_logger.setLevel(settings.LOG_LEVEL)
    app_logger.propagate = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _setup_logging()
    preload_model()
    yield


app = FastAPI(title="LiveFactChecker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FactCheckRequest(BaseModel):
    text: str
    web_search: bool = True


class LoginRequest(BaseModel):
    password: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/login")
async def admin_login(req: LoginRequest):
    if not check_password(req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mot de passe incorrect",
        )
    return {"token": create_token()}


@app.post("/fact-check")
async def fact_check(req: FactCheckRequest, _admin: str = Depends(require_admin)):
    results = await extract_and_verify(req.text, web_search=req.web_search)
    return {"text": req.text, "claims": results}


@app.get("/admin/health")
async def admin_health(_admin: str = Depends(require_admin)):
    data: dict = {
        "uptime_seconds": int(time.time() - _start_time),
        "whisper": {
            "model": settings.WHISPER_MODEL,
            "device": settings.WHISPER_DEVICE,
            "loaded": is_model_loaded(),
        },
        "anthropic": {
            "model": settings.ANTHROPIC_MODEL,
            "api_key_set": bool(settings.ANTHROPIC_API_KEY),
            "api_key_hint": f"...{settings.ANTHROPIC_API_KEY[-4:]}"
            if settings.ANTHROPIC_API_KEY
            else "",
        },
        "config": {
            "log_level": settings.LOG_LEVEL,
            "jwt_expire_hours": settings.JWT_EXPIRE_HOURS,
            "max_claims_per_chunk": settings.MAX_CLAIMS_PER_CHUNK,
        },
        "python_version": sys.version.split()[0],
    }
    try:
        proc = psutil.Process()
        mem = proc.memory_info()
        data["memory"] = {
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
        }
    except ImportError:
        pass
    return data


@app.get("/admin/prompt")
async def admin_prompt(_admin: str = Depends(require_admin)):
    return {
        "system_prompt": SYSTEM_PROMPT,
        "claim_tool": CLAIM_TOOL,
        "web_search_tool": WEB_SEARCH_TOOL,
        "valid_statuses": list(VALID_STATUSES),
        "min_words": MIN_WORDS,
        "model": settings.ANTHROPIC_MODEL,
    }


_EDITABLE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-8",
]
_VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class ConfigPatch(BaseModel):
    anthropic_model: str | None = None
    log_level: str | None = None


@app.get("/admin/config")
async def admin_config(_admin: str = Depends(require_admin)):
    return {
        "editable": {
            "anthropic_model": settings.ANTHROPIC_MODEL,
            "log_level": settings.LOG_LEVEL,
        },
        "readonly": {
            "whisper_model": settings.WHISPER_MODEL,
            "whisper_device": settings.WHISPER_DEVICE,
            "jwt_expire_hours": settings.JWT_EXPIRE_HOURS,
            "max_claims_per_chunk": settings.MAX_CLAIMS_PER_CHUNK,
        },
        "options": {
            "models": _EDITABLE_MODELS,
            "log_levels": _VALID_LOG_LEVELS,
        },
        "note": "Les modifications sont perdues au redémarrage (--reload actif).",
    }


@app.patch("/admin/config")
async def patch_config(patch: ConfigPatch, _admin: str = Depends(require_admin)):
    changed: dict = {}
    if patch.anthropic_model is not None:
        if patch.anthropic_model not in _EDITABLE_MODELS:
            raise HTTPException(
                status_code=422, detail=f"Modèle inconnu : {patch.anthropic_model}"
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
    return {"changed": changed}


@app.get("/admin/logs")
async def admin_logs(
    after: int = Query(default=0, ge=0),
    _admin: str = Depends(require_admin),
):
    entries = [e for e in _log_history if e["id"] > after]
    return {"entries": entries}


@app.get("/admin/ws/status")
async def admin_ws_status(_admin: str = Depends(require_admin)):
    return get_sessions_status()


@app.post("/admin/whisper/transcribe")
async def admin_whisper_transcribe(
    file: UploadFile = File(...),
    _admin: str = Depends(require_admin),
):
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Fichier vide")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, transcribe_with_detail, audio_bytes)
    return result


class ModelTestRequest(BaseModel):
    text: str
    web_search: bool = True


@app.post("/admin/model-test")
async def admin_model_test(
    req: ModelTestRequest,
    _admin: str = Depends(require_admin),
):
    return await debug_extract(req.text, web_search=req.web_search)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await run_session(ws)
