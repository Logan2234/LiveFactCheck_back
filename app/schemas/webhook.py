"""Request/response schemas for the webhook routes."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas.claim import VerificationStatus


class WebhookKind(StrEnum):
    """Destination type — picked by the user, drives the outgoing payload format.

    SLACK / DISCORD send that service's native message field; CUSTOM sends our
    structured JSON (for any other app the user integrates themselves).
    """

    SLACK = "slack"
    DISCORD = "discord"
    CUSTOM = "custom"


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    kind: WebhookKind = WebhookKind.CUSTOM
    # At least one status must fire the webhook; defaults to debunked ("false") claims.
    trigger_statuses: list[VerificationStatus] = Field(
        default=[VerificationStatus.FALSE], min_length=1
    )


class WebhookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str
    kind: WebhookKind
    trigger_statuses: list[str]
    enabled: bool
    # Returned to the owner so they can configure HMAC verification on their receiver.
    secret: str
    created_at: datetime
    last_triggered_at: datetime | None
    last_error: str | None
    failure_count: int
