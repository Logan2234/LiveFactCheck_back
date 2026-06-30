"""Persistence for user-registered webhooks.

Synchronous SQLAlchemy helpers taking an explicit ``Session``. The HTTP routes pass the
request-scoped ``get_db`` session (testable via override); the live WS path opens its
own ``SessionLocal`` around these calls (see ``services/session.py``). Ownership is
always checked against ``user_id`` so a user can only touch their own webhooks.
"""

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models import Webhook
from app.services.session_store import utcnow


def create(
    db: DBSession,
    *,
    user_id: str,
    name: str,
    url: str,
    kind: str,
    trigger_statuses: list[str],
) -> Webhook:
    webhook = Webhook(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=name,
        url=url,
        kind=kind,
        secret=secrets.token_urlsafe(32),
        trigger_statuses=trigger_statuses,
        enabled=True,
        created_at=utcnow(),
        failure_count=0,
    )
    db.add(webhook)
    db.commit()
    return webhook


def list_for_user(db: DBSession, user_id: str) -> list[Webhook]:
    return list(
        db.execute(
            select(Webhook)
            .where(Webhook.user_id == user_id)
            .order_by(Webhook.created_at)
        ).scalars()
    )


def list_enabled_for_user(db: DBSession, user_id: str) -> list[Webhook]:
    return list(
        db.execute(
            select(Webhook).where(Webhook.user_id == user_id, Webhook.enabled.is_(True))
        ).scalars()
    )


def get(db: DBSession, webhook_id: str, user_id: str) -> Webhook | None:
    webhook = db.get(Webhook, webhook_id)
    if webhook is None or webhook.user_id != user_id:
        return None
    return webhook


def delete(db: DBSession, webhook_id: str, user_id: str) -> bool:
    webhook = get(db, webhook_id, user_id)
    if webhook is None:
        return False
    db.delete(webhook)
    db.commit()
    return True


def record_delivery(
    db: DBSession, webhook_id: str, ok: bool, error: str | None
) -> None:
    """Update delivery health after an attempt (no-op if the webhook is gone)."""
    webhook = db.get(Webhook, webhook_id)
    if webhook is None:
        return
    webhook.last_triggered_at = utcnow()
    if ok:
        webhook.last_error = None
    else:
        webhook.last_error = (error or "")[:500]
        webhook.failure_count += 1
    db.commit()
