"""WebSocket entry point: audio chunks → transcript → claims.

The route only accepts the socket and hands it to the session service; all
orchestration lives in ``app.services.session``.
"""

from fastapi import APIRouter, WebSocket

from app.services.session import run_session

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await run_session(ws)
