"""WebSocket session orchestration: audio chunk → transcript → claims.

One :func:`run_session` call drives a single connection for its whole lifetime.
Keeping this out of the API layer lets ``main.py`` hold nothing but endpoint
definitions.
"""

import asyncio
import json
import logging
import time
import uuid

from fastapi import WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.core.languages import normalize_language
from app.schemas.claim import Claim, ConfigMessage, VerificationStatus
from app.services.claim_extractor import MIN_WORDS, extract_and_verify
from app.services.transcription import transcribe_chunk

logger = logging.getLogger(__name__)

_active_sessions: dict[str, dict] = {}
_total_sessions = 0


def get_sessions_status() -> dict:
    now = time.time()
    sessions = [
        {
            "id": s["id"],
            "connected_at": s["connected_at"],
            "client": s["client"],
            "chunks_received": s["chunks_received"],
            "transcripts": s["transcripts"],
            "claims_spawned": s["claims_spawned"],
            "active_tasks": len(s["_tasks"]),
            "last_transcript": s["last_transcript"],
            "language": s["language"] or "auto",
            "idle_s": round(now - s["last_activity"]),
        }
        for s in _active_sessions.values()
    ]
    return {"active": sessions, "total_since_start": _total_sessions}


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
    ws: WebSocket,
    transcript: str,
    background_tasks: set[asyncio.Task],
    session_info: dict,
):
    """Fire claim extraction for a transcribed chunk, tracking the task."""
    if len(transcript.split()) < MIN_WORDS:
        return
    session_info["claims_spawned"] += 1
    task = asyncio.create_task(_process_claims(ws, transcript))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


def parse_config_language(raw: str) -> str | None:
    """Extract a normalized transcription language from a client config frame.

    ``raw`` is the text payload of a WebSocket frame. Returns the language to use
    (``None`` for auto-detect, or a supported ISO code), or raises ``ValueError``
    if the frame isn't a valid ``config`` message — the caller logs and ignores
    it rather than dropping the session.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    if not isinstance(data, dict) or data.get("type") != "config":
        raise ValueError("not a config message")
    try:
        msg = ConfigMessage.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"invalid config message: {e}") from e
    return normalize_language(msg.language)


async def run_session(ws: WebSocket):
    """Drive one WebSocket connection: receive chunks, transcribe, fact-check.

    The client records ~5 s slices with MediaRecorder and sends each as a
    complete WebM/Opus blob (binary frame). We transcribe the blob in one pass
    and fire claim extraction on the resulting text. Sentences may be split
    across chunk boundaries — this is the simple baseline.
    """
    global _total_sessions
    await ws.accept()
    loop = asyncio.get_event_loop()
    background_tasks: set[asyncio.Task] = set()

    session_id = str(uuid.uuid4())
    _total_sessions += 1
    client_host = ws.client.host if ws.client else "unknown"
    session_info: dict = {
        "id": session_id,
        "connected_at": time.time(),
        "client": client_host,
        "chunks_received": 0,
        "transcripts": 0,
        "claims_spawned": 0,
        "_tasks": background_tasks,
        "last_transcript": "",
        # Transcription language: None = auto-detect (the default until the
        # client sends a config frame), or a forced ISO code.
        "language": None,
        "last_activity": time.time(),
    }
    _active_sessions[session_id] = session_info
    logger.info("WS session %s opened from %s", session_id[:8], client_host)

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break

            # Text frames carry session config (e.g. the chosen language); binary
            # frames carry audio. A malformed config is logged and ignored.
            config = message.get("text")
            if config is not None:
                try:
                    session_info["language"] = parse_config_language(config)
                    logger.info(
                        "WS session %s language set to %s",
                        session_id[:8],
                        session_info["language"] or "auto",
                    )
                except ValueError as e:
                    logger.warning("Ignoring config frame: %s", e)
                continue

            audio = message.get("bytes")
            if not audio:
                continue

            # Drop an oversized blob instead of killing the session: one bad
            # chunk shouldn't end a legitimate live stream.
            if len(audio) > settings.MAX_AUDIO_BYTES:
                logger.warning(
                    "Dropping oversized audio chunk: %d bytes (max %d)",
                    len(audio),
                    settings.MAX_AUDIO_BYTES,
                )
                continue

            session_info["chunks_received"] += 1
            session_info["last_activity"] = time.time()

            language = session_info["language"]
            try:
                transcript, detected_lang, detected_prob = await loop.run_in_executor(
                    None, transcribe_chunk, audio, language
                )
            except Exception as e:
                logger.error("Transcription error: %s", e)
                continue

            if not transcript:
                continue

            session_info["transcripts"] += 1
            session_info["last_transcript"] = transcript[:120]
            session_info["last_activity"] = time.time()

            logger.info(transcript)
            # Report the detected language only in auto mode (it's None otherwise).
            message_out: dict = {"type": "transcript", "text": transcript}
            if detected_lang is not None:
                message_out["language"] = detected_lang
                message_out["language_probability"] = detected_prob
            await ws.send_json(message_out)
            _spawn_claims(ws, transcript, background_tasks, session_info)

    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is raised by ws.receive() once the socket is disconnected.
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        _active_sessions.pop(session_id, None)
        logger.info("WS session %s closed", session_id[:8])
        for task in background_tasks:
            task.cancel()
