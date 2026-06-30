"""Webhook registration routes (per user, gated by ``require_user``).

A user manages only their own webhooks: every handler resolves the caller's id from the
token and scopes the query to it. Handlers are plain ``def`` so FastAPI runs the sync DB
work in its threadpool.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.db.session import get_db
from app.dependencies import require_user
from app.schemas.webhook import WebhookCreate, WebhookOut
from app.services import webhook_store

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
def create_webhook(
    req: WebhookCreate,
    user_id: str = Depends(require_user),
    db: DBSession = Depends(get_db),
) -> WebhookOut:
    webhook = webhook_store.create(
        db,
        user_id=user_id,
        name=req.name,
        url=str(req.url),
        kind=req.kind.value,
        trigger_statuses=[s.value for s in req.trigger_statuses],
    )
    return WebhookOut.model_validate(webhook)


@router.get("", response_model=list[WebhookOut])
def list_webhooks(
    user_id: str = Depends(require_user),
    db: DBSession = Depends(get_db),
) -> list[WebhookOut]:
    return [
        WebhookOut.model_validate(w) for w in webhook_store.list_for_user(db, user_id)
    ]


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: str,
    user_id: str = Depends(require_user),
    db: DBSession = Depends(get_db),
) -> None:
    if not webhook_store.delete(db, webhook_id, user_id):
        raise HTTPException(status_code=404, detail="Webhook introuvable")
