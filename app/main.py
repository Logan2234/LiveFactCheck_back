import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/fact-check")
async def fact_check(req: FactCheckRequest):
    results = await extract_and_verify(req.text)
    return {"text": req.text, "claims": results}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await run_session(ws)
