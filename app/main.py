"""FastAPI app assembly only: lifespan, middleware, router mounting.

No routes, business logic or config live here (see app/api/routers/, app/services/,
app/config.py). The lifespan preloads the Whisper model and wires up logging.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    admin,
    auth,
    fact_check,
    health,
    sessions,
    users,
    webhooks,
    ws,
)
from app.config import settings
from app.core.observability import setup_logging
from app.db.session import init_db
from app.services.transcription import preload_model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    init_db()
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

# /health stays unversioned (infra probe convention). Every other router is mounted
# under /v1 so the API is versioned in one place — the prefix also moves /ws to /v1/ws.
app.include_router(health.router)

API_V1 = "/v1"
app.include_router(auth.router, prefix=API_V1)
app.include_router(fact_check.router, prefix=API_V1)
app.include_router(admin.router, prefix=API_V1)
app.include_router(sessions.router, prefix=API_V1)
app.include_router(users.router, prefix=API_V1)
app.include_router(webhooks.router, prefix=API_V1)
app.include_router(ws.router, prefix=API_V1)
