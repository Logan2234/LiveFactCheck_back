import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.services.auth import check_password, create_token, require_admin
from app.services.claim_extractor import extract_and_verify
from app.services.session import run_session
from app.services.transcription import preload_model


def _setup_logging() -> None:
    """Route the app's loggers through uvicorn's handlers.

    Uvicorn only configures its own loggers, so ``app.*`` loggers stay at the
    root's default level (WARNING) and their info logs are dropped. We hand them
    uvicorn's handler/level so they show up with the same format.
    """
    uvicorn_logger = logging.getLogger("uvicorn")
    app_logger = logging.getLogger("app")
    app_logger.handlers = uvicorn_logger.handlers
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


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await run_session(ws)
