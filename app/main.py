import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.models.schemas import Claim, VerificationStatus
from app.services.claim_extractor import MIN_WORDS, extract_and_verify
from app.services.transcription import preload_model, transcribe_audio


@asynccontextmanager
async def lifespan(_app: FastAPI):
    preload_model()
    yield


app = FastAPI(title="LiveFactChecker API", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

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
        pending = Claim(id=pending_id, text=transcript, status=VerificationStatus.PENDING, timestamp=pending_ts)
        await ws.send_json({"type": "claim", "claim": pending.model_dump()})

        results = await extract_and_verify(transcript)

        if not results:
            await ws.send_json({"type": "remove_claim", "id": pending_id})
            return

        first, *rest = results
        await ws.send_json({"type": "claim", "claim": _make_claim(first, pending_id, pending_ts).model_dump()})

        for result in rest:
            await ws.send_json({
                "type": "claim",
                "claim": _make_claim(result, str(uuid.uuid4()), int(time.time() * 1000)).model_dump(),
            })

    except Exception as e:
        print(f"Claim processing error: {e}")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    background_tasks: set[asyncio.Task] = set()
    try:
        while True:
            audio_data = await ws.receive_bytes()

            try:
                transcript = await transcribe_audio(audio_data)
            except Exception as e:
                print(f"Transcription error: {e}")
                continue

            if not transcript.strip():
                continue

            await ws.send_json({"type": "transcript", "text": transcript})

            if len(transcript.split()) >= MIN_WORDS:
                task = asyncio.create_task(process_claims(ws, transcript))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        for task in background_tasks:
            task.cancel()
