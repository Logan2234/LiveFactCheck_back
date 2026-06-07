import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.models.schemas import Claim, VerificationStatus
from app.services.claim_extractor import MIN_WORDS, extract_and_verify
from app.services.transcription import preload_model, transcribe_chunk


@asynccontextmanager
async def lifespan(_app: FastAPI):
    preload_model()
    yield


app = FastAPI(title="LiveFactChecker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


class FactCheckRequest(BaseModel):
    text: str


@app.post("/fact-check")
async def fact_check(req: FactCheckRequest):
    results = await extract_and_verify(req.text)
    return {"text": req.text, "claims": results}


async def process_claims(ws: WebSocket, transcript: str):
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
            await ws.send_json(
                {
                    "type": "claim",
                    "claim": _make_claim(
                        result, str(uuid.uuid4()), int(time.time() * 1000)
                    ).model_dump(),
                }
            )

    except Exception as e:
        print(f"Claim processing error: {e}")


def _spawn_claims(ws: WebSocket, transcript: str, background_tasks: set[asyncio.Task]):
    """Fire claim extraction for a transcribed chunk."""
    if len(transcript.split()) < MIN_WORDS:
        return
    task = asyncio.create_task(process_claims(ws, transcript))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Receive self-contained audio chunks, transcribe each, then fact-check.

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
                transcript = await loop.run_in_executor(
                    None, transcribe_chunk, audio
                )
            except Exception as e:
                print(f"Transcription error: {e}")
                continue

            if not transcript:
                continue

            await ws.send_json({"type": "transcript", "text": transcript})
            _spawn_claims(ws, transcript, background_tasks)

    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is raised by ws.receive() once the socket is disconnected.
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        for task in background_tasks:
            task.cancel()
