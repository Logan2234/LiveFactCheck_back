"""WebSocket session orchestration: audio chunk → transcript → claims.

One :func:`run_session` call drives a single connection for its whole lifetime.
Keeping this out of the API layer lets ``main.py`` hold nothing but endpoint
definitions.
"""

import asyncio
import logging
import time
import uuid

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.models.schemas import Claim, VerificationStatus
from app.services.claim_extractor import MIN_WORDS, extract_and_verify
from app.services.transcription import transcribe_chunk

logger = logging.getLogger(__name__)


def _make_claim(result: dict, claim_id: str, timestamp: int) -> Claim:
    return Claim(
        id=claim_id,
        text=result["text"],
        status=VerificationStatus(result["status"]),
        explanation=result["explanation"],
        sources=result.get("sources", []),
        timestamp=timestamp,
        category=result.get("category", ""),
        confidence=result.get("confidence", 0),
        counter_claim=result.get("counter_claim", ""),
        web_search_used=result.get("web_search_used", False),
    )


async def _process_claims(ws: WebSocket, transcript: str):
    """Show a pending claim, then replace/remove it with the verified results."""
    try:
        pending_id = str(uuid.uuid4())
        pending_ts = int(time.time() * 1000)
        pending = Claim(
            id=pending_id,
            text=transcript,
            status=VerificationStatus.PENDING,
            timestamp=pending_ts,
        )
        await ws.send_json({"type": "claim", "claim": pending.model_dump()})

        results = await extract_and_verify(transcript)
        if not results:
            await ws.send_json({"type": "remove_claim", "id": pending_id})
            return

        first, *rest = results
        await ws.send_json(
            {
                "type": "claim",
                "claim": _make_claim(first, pending_id, pending_ts).model_dump(),
            }
        )
        for result in rest:
            claim = _make_claim(result, str(uuid.uuid4()), int(time.time() * 1000))
            await ws.send_json({"type": "claim", "claim": claim.model_dump()})

    except Exception as e:
        logger.error("Claim processing error: %s", e)


def _spawn_claims(
    ws: WebSocket, transcript: str, background_tasks: set[asyncio.Task]
):
    """Fire claim extraction for a transcribed chunk, tracking the task."""
    if len(transcript.split()) < MIN_WORDS:
        return
    task = asyncio.create_task(_process_claims(ws, transcript))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def run_session(ws: WebSocket):
    """Drive one WebSocket connection: receive chunks, transcribe, fact-check.

    The client records ~5 s slices with MediaRecorder and sends each as a
    complete WebM/Opus blob (binary frame). We transcribe the blob in one pass
    and fire claim extraction on the resulting text. Sentences may be split
    across chunk boundaries — this is the simple baseline.
    """
    await ws.accept()
    loop = asyncio.get_event_loop()
    background_tasks: set[asyncio.Task] = set()

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break

            audio = message.get("bytes")
            if not audio:
                continue

            try:
                transcript = await loop.run_in_executor(None, transcribe_chunk, audio)
            except Exception as e:
                logger.error("Transcription error: %s", e)
                continue

            if not transcript:
                continue

            logger.info(transcript)
            await ws.send_json({"type": "transcript", "text": transcript})
            _spawn_claims(ws, transcript, background_tasks)

    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is raised by ws.receive() once the socket is disconnected.
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        for task in background_tasks:
            task.cancel()
