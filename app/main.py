"""FastAPI app assembly only: lifespan, middleware, router mounting.

No routes, business logic or config live here (see app/api/routers/, app/services/,
app/config.py). The lifespan preloads the Whisper model and wires up logging.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import admin, auth, fact_check, health, ws
from app.config import settings
from app.core.observability import setup_logging
from app.services.transcription import preload_model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    preload_model()
    yield


app = FastAPI(title="LiveFactChecker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(fact_check.router)
app.include_router(admin.router)
app.include_router(ws.router)
