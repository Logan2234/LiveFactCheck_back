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
from collections import OrderedDict, deque

import numpy as np
from fastapi import WebSocket
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.core.languages import normalize_language
from app.schemas.claim import (
    Claim,
    ConfigMessage,
    VerificationLevel,
    VerificationStatus,
)
from app.services import session_store
from app.services.audio_endpointer import Endpointer, silero_vad
from app.services.claim_extractor import MIN_WORDS, extract_and_verify
from app.services.normalize import normalize
from app.services.transcription import transcribe_samples

logger = logging.getLogger(__name__)

# Upper bound on a session's seen-claim registry, so a long session can't grow it
# without limit. Oldest entries are evicted; a repeated claim further back than
# this could re-appear once, which is acceptable.
SEEN_CLAIMS_MAX = 200

# Live registry of currently-open WebSocket connections, keyed by session id.
# This is runtime state, NOT a cache of the DB: each value holds live Python
# objects (the set of in-flight asyncio.Tasks, the rolling-context deque) and
# sub-second counters that are never persisted. Its sole reader is
# get_sessions_status() -> GET /admin/ws/status (the live monitor page).
#
# Limitation — single process only: with multiple uvicorn workers each worker
# sees only its own connections, and the registry doesn't survive a restart.
# It cannot be replaced by DB queries: the DB tracks *history* (rows created
# lazily on first transcript, closed on disconnect), not who is connected now.
_active_sessions: dict[str, dict] = {}
_total_sessions = 0


async def _persist(fn, *args, **kwargs) -> None:
    """Run a session_store write off the event loop, best-effort.

    Persistence must never drop a live session: a DB error is logged and
    swallowed, and the whole call is skipped when PERSIST_SESSIONS is off.
    """
    if not settings.PERSIST_SESSIONS:
        return
    try:
        await asyncio.to_thread(fn, *args, **kwargs)
    except SQLAlchemyError as e:
        logger.error("Persistence error in %s: %s", fn.__name__, e)


async def _ensure_persisted(session_info: dict) -> None:
    """Create the session row lazily, on the first transcript.

    A connection that opens and closes without ever producing a transcript leaves
    no row behind — no empty session clutters the history. Called from the
    sequential utterance loop, so the create-once guard needs no locking.
    """
    if session_info["persisted"]:
        return
    session_info["persisted"] = True
    await _persist(
        session_store.create_session,
        session_info["id"],
        session_info["client"],
        session_info["started_at"],
    )


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


def _dedupe_claims(claims: list[dict], seen: "OrderedDict[str, None]") -> list[dict]:
    """Drop claims whose normalized text was already emitted in this session.

    Mutates ``seen`` (adds each kept claim's key, evicting oldest past the bound).
    Pure and synchronous on purpose: the concurrent claim tasks share one session
    registry, and running this without an await in between keeps the check-and-add
    atomic against the event loop, so they don't race.
    """
    kept: list[dict] = []
    for claim in claims:
        key = normalize(claim["text"])
        if key in seen:
            continue
        seen[key] = None
        kept.append(claim)
    while len(seen) > SEEN_CLAIMS_MAX:
        seen.popitem(last=False)
    return kept


async def _process_claims(
    ws: WebSocket,
    transcript: str,
    context: list[str],
    web_search: bool,
    session_id: str,
    segment_id: str,
    seen_claims: "OrderedDict[str, None]",
):
    """Show a pending claim, then replace/remove it with the verified results.

    Also records the verification measurements on the segment and persists each
    final claim (never the transient pending placeholder). Claims already emitted
    in this session are dropped, so a fact repeated across utterances shows once.
    """
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

        started = time.perf_counter()
        result = await extract_and_verify(
            transcript, context=context, web_search=web_search
        )
        verify_ms = (time.perf_counter() - started) * 1000.0
        await _persist(
            session_store.set_segment_metrics,
            segment_id,
            verify_ms=verify_ms,
            usage=result.usage,
            api_calls=result.api_calls,
            web_search_calls=result.web_search_calls,
        )

        # Drop claims already shown this session (a fact repeated across utterances
        # shouldn't spawn a second card). All-duplicate is handled like no-claims:
        # the pending placeholder is removed.
        new_claims = _dedupe_claims(result.claims, seen_claims)
        if not new_claims:
            await ws.send_json({"type": "remove_claim", "id": pending_id})
            return

        first, *rest = new_claims
        first_claim = _make_claim(first, pending_id, pending_ts).model_dump()
        await ws.send_json({"type": "claim", "claim": first_claim})
        await _persist(session_store.add_claim, first_claim, session_id, segment_id)
        for extra in rest:
            claim = _make_claim(
                extra, str(uuid.uuid4()), int(time.time() * 1000)
            ).model_dump()
            await ws.send_json({"type": "claim", "claim": claim})
            await _persist(session_store.add_claim, claim, session_id, segment_id)

    except Exception as e:
        logger.error("Claim processing error: %s", e)


def _spawn_claims(
    ws: WebSocket,
    transcript: str,
    context: list[str],
    background_tasks: set[asyncio.Task],
    session_info: dict,
    segment_id: str,
):
    """Fire claim extraction for a transcribed chunk, tracking the task."""
    if len(transcript.split()) < MIN_WORDS:
        return
    session_info["claims_spawned"] += 1
    # THOROUGH offers the web_search tool; FAST keeps verification to internal
    # knowledge for a single, faster API call.
    web_search = session_info["verification_level"] == VerificationLevel.THOROUGH
    task = asyncio.create_task(
        _process_claims(
            ws,
            transcript,
            context,
            web_search,
            session_info["id"],
            segment_id,
            session_info["seen_claims"],
        )
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def _emit_utterance(
    ws: WebSocket,
    segment: np.ndarray,
    session_info: dict,
    background_tasks: set[asyncio.Task],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Transcribe one endpointed utterance and emit its transcript + claims."""
    # Always transcribe in auto-detect: forcing a language would make Whisper
    # translate a mismatched utterance instead of transcribing it.
    started = time.perf_counter()
    try:
        transcript, detected_lang, detected_prob = await loop.run_in_executor(
            None, transcribe_samples, segment
        )
    except Exception as e:
        logger.error("Transcription error: %s", e)
        return
    transcribe_ms = (time.perf_counter() - started) * 1000.0

    if not transcript:
        return

    # The chosen language is a filter, not a forced transcription target: drop an
    # utterance whose detected language doesn't match (None = accept all).
    language = session_info["language"]
    if language is not None and detected_lang != language:
        logger.info(
            "Skipping utterance: detected %s, session filter is %s",
            detected_lang,
            language,
        )
        return

    session_info["transcripts"] += 1
    session_info["last_transcript"] = transcript[:120]
    session_info["last_activity"] = time.time()

    logger.info(transcript)
    await ws.send_json(
        {
            "type": "transcript",
            "text": transcript,
            "language": detected_lang,
            "language_probability": detected_prob,
        }
    )

    # Create the session row on the first transcript, then persist the segment
    # before spawning verification, so the background task's metrics update and
    # any linked claims have a parent row to reference.
    await _ensure_persisted(session_info)
    segment_id = str(uuid.uuid4())
    seq = session_info["seq"]
    session_info["seq"] += 1
    await _persist(
        session_store.add_segment,
        segment_id=segment_id,
        session_id=session_info["id"],
        seq=seq,
        text=transcript,
        detected_language=detected_lang,
        language_probability=detected_prob,
        transcribe_ms=transcribe_ms,
    )

    # Snapshot the preceding utterances *before* adding the current one, so a
    # back-reference ("Il en est de même de…") can be resolved against them. The
    # list() copy is what the background task reads, immune to later mutations.
    context = list(session_info["context"])
    _spawn_claims(ws, transcript, context, background_tasks, session_info, segment_id)
    session_info["context"].append(transcript)


def _make_endpointer() -> Endpointer:
    """Build a per-session endpointer from the current VAD settings.

    Reads settings at session start, so a runtime ``/admin/config`` change applies
    to new sessions (an existing live session keeps the config it opened with).
    """
    return Endpointer(
        silence_flush_ms=settings.VAD_SILENCE_FLUSH_MS,
        max_segment_ms=settings.VAD_MAX_SEGMENT_MS,
        min_segment_ms=settings.VAD_MIN_SEGMENT_MS,
        vad_fn=silero_vad(settings.VAD_THRESHOLD),
    )


def parse_config(raw: str) -> ConfigMessage:
    """Parse and validate a client config frame.

    ``raw`` is the text payload of a WebSocket frame. Returns the validated
    ``ConfigMessage`` (the caller normalizes ``language`` and reads
    ``verification_level``), or raises ``ValueError`` if the frame isn't a valid
    ``config`` message — the caller logs and ignores it rather than dropping the
    session.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    if not isinstance(data, dict) or data.get("type") != "config":
        raise ValueError("not a config message")
    try:
        return ConfigMessage.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"invalid config message: {e}") from e


async def run_session(ws: WebSocket):
    """Drive one WebSocket connection: receive PCM, endpoint, transcribe, fact-check.

    The client streams raw PCM continuously (16 kHz mono Int16 frames, binary). We
    buffer it and cut utterances on natural pauses with a VAD endpointer instead of
    fixed client-side chunks — so words/sentences are no longer split every 5 s and
    no audio is dropped at chunk boundaries. Each completed utterance is transcribed
    and fed to claim extraction.
    """
    global _total_sessions
    # Public-beta guardrail: refuse a new connection once we're at capacity, before
    # the handshake — a rejected client costs no session_info, no endpointer and no
    # Whisper work. (Tiny race: two connections can both pass this check across the
    # accept await below; acceptable for a beta — at worst a couple over the cap.)
    if (
        settings.MAX_CONCURRENT_SESSIONS
        and len(_active_sessions) >= settings.MAX_CONCURRENT_SESSIONS
    ):
        await ws.close(code=1013, reason="server at capacity")  # 1013 = Try Again Later
        logger.warning(
            "Refused WS connection: at capacity (%d active)",
            settings.MAX_CONCURRENT_SESSIONS,
        )
        return

    await ws.accept()
    loop = asyncio.get_event_loop()
    background_tasks: set[asyncio.Task] = set()
    endpointer = _make_endpointer()

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
        # Rolling window of recent transcripts, handed to claim extraction as
        # read-only context so an utterance that references the previous one can
        # be resolved instead of dropped as unverifiable.
        "context": deque(maxlen=settings.CONTEXT_TURNS),
        # Transcription language: None = auto-detect (the default until the
        # client sends a config frame), or a forced ISO code.
        "language": None,
        # Speed/depth trade-off for fact-checking; THOROUGH (web_search allowed)
        # until the client says otherwise, matching the prior default.
        "verification_level": VerificationLevel.THOROUGH,
        "last_activity": time.time(),
        # Monotonic sequence number for persisted transcript segments.
        "seq": 0,
        # Normalized texts of claims already emitted this session, so a fact
        # repeated across utterances shows a single card. Bounded LRU registry.
        "seen_claims": OrderedDict(),
        # The session row is created lazily on the first transcript (see
        # _ensure_persisted), so an empty connection leaves no row. started_at is
        # captured now so the row reflects the real connect time, not first speech.
        "started_at": session_store.utcnow(),
        "persisted": False,
    }
    _active_sessions[session_id] = session_info
    logger.info("WS session %s opened from %s", session_id[:8], client_host)

    # Absolute deadline for the public-beta duration cap (None = no limit). We only
    # enforce it around ws.receive(): a busy client streaming PCM non-stop is cut by
    # the elapsed-time check, an idle one by bounding the receive() wait. An in-flight
    # transcription/verification is never interrupted — only the next frame is refused.
    max_duration = settings.MAX_SESSION_DURATION_SECONDS
    deadline = loop.time() + max_duration if max_duration else None

    try:
        while True:
            if deadline is not None and loop.time() >= deadline:
                await ws.close(code=4000, reason="session time limit")
                break
            if deadline is not None:
                try:
                    message = await asyncio.wait_for(
                        ws.receive(), timeout=deadline - loop.time()
                    )
                except TimeoutError:
                    await ws.close(code=4000, reason="session time limit")
                    break
            else:
                message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break

            # Text frames carry session config (e.g. the chosen language); binary
            # frames carry audio. A malformed config is logged and ignored.
            config = message.get("text")
            if config is not None:
                try:
                    cfg = parse_config(config)
                    session_info["language"] = normalize_language(cfg.language)
                    session_info["verification_level"] = cfg.verification_level
                    logger.info(
                        "WS session %s config: language=%s verification=%s",
                        session_id[:8],
                        session_info["language"] or "auto",
                        session_info["verification_level"].value,
                    )
                except ValueError as e:
                    logger.warning("Ignoring config frame: %s", e)
                continue

            audio = message.get("bytes")
            if not audio:
                continue

            # Drop an oversized frame instead of killing the session: one bad
            # frame shouldn't end a legitimate live stream.
            if len(audio) > settings.MAX_AUDIO_BYTES:
                logger.warning(
                    "Dropping oversized audio frame: %d bytes (max %d)",
                    len(audio),
                    settings.MAX_AUDIO_BYTES,
                )
                continue

            # Each binary frame is raw Int16 LE PCM @ 16 kHz mono. An odd byte
            # count means a torn frame — skip it rather than mis-decode/crash.
            if len(audio) % 2 != 0:
                logger.warning("Dropping PCM frame with odd byte count: %d", len(audio))
                continue

            session_info["chunks_received"] += 1
            session_info["last_activity"] = time.time()

            samples = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
            endpointer.add(samples)

            # Drain every utterance the pause/length policy has completed. pop()
            # runs the VAD (CPU-bound), so it goes through the executor.
            while True:
                segment = await loop.run_in_executor(None, endpointer.pop)
                if segment is None:
                    break
                await _emit_utterance(ws, segment, session_info, background_tasks, loop)

    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is raised by ws.receive() once the socket is disconnected.
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        _active_sessions.pop(session_id, None)
        # Only finalize a row that was actually created (a session with no
        # transcript was never persisted, so there's nothing to close).
        if session_info["persisted"]:
            await _persist(
                session_store.end_session,
                session_id,
                session_store.utcnow(),
                session_info["chunks_received"],
            )
        logger.info("WS session %s closed", session_id[:8])
        for task in background_tasks:
            task.cancel()
