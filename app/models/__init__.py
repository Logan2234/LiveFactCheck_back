"""ORM models (database tables).

Importing this package registers every model on ``Base.metadata`` (so
``init_db`` can create the tables). Models stay distinct from the Pydantic API
schemas in ``app/schemas/`` (see .claude/rules/architecture.md); convert
explicitly across the boundary.
"""

from app.models.claim import Claim
from app.models.session import Session
from app.models.transcript_segment import TranscriptSegment

__all__ = ["Claim", "Session", "TranscriptSegment"]
