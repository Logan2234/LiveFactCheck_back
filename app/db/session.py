"""SQLAlchemy engine, session factory and schema bootstrap.

The app is async but persistence uses the *sync* SQLAlchemy API: writes on the WS
path are offloaded to a thread (``asyncio.to_thread``, like transcription), and the
read routes are plain ``def`` handlers that FastAPI runs in its threadpool. This
keeps the dependency surface minimal (no aiosqlite) and matches the existing
"offload blocking work to a thread" pattern.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.base import Base

# SQLite refuses cross-thread connection reuse by default; we hand connections to
# threadpool workers, so disable that guard. SQLAlchemy still gives each Session
# its own connection from the pool, so this stays safe.
_connect_args = (
    {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args)

# expire_on_commit=False lets a committed ORM object still be read (its attributes
# stay populated) after the transaction closes — convenient for short write helpers.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create any missing tables. Idempotent; called once at startup."""
    # Import the models so they register on Base.metadata before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a DB session, closed in a finally."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
