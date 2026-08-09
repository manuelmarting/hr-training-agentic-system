"""Standalone Kokoro-82M TTS service. One endpoint, no persistence, no auth — the
chat backend treats this as a best-effort side output (see backend/app/agent/tts.py)
and keeps working text-only if this service is slow or down.

The KPipeline is loaded once at startup and kept warm: cold pipeline init takes
several seconds (model + voice load), but a warm `pipeline(text)` call is well
under a second for a typical reply, so one long-lived process beats spinning up
a pipeline per request.
"""

import asyncio
import io
import logging
from contextlib import asynccontextmanager
from typing import Literal

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Response
from kokoro import KPipeline
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000

_pipeline: KPipeline | None = None
_state: Literal["initializing", "ready", "error"] = "initializing"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline, _state
    try:
        loop = asyncio.get_event_loop()
        _pipeline = await loop.run_in_executor(None, lambda: KPipeline(lang_code="a"))
        _state = "ready"
    except Exception:
        _state = "error"
        logger.exception("kokoro pipeline failed to initialize")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": _state}


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "af_heart"


@app.post("/synthesize")
async def synthesize(request: SynthesizeRequest) -> Response:
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="model not ready")

    loop = asyncio.get_event_loop()
    audio_bytes = await loop.run_in_executor(
        None, lambda: _generate(_pipeline, request.text, request.voice)
    )
    return Response(content=audio_bytes, media_type="audio/wav")


def _generate(pipeline: KPipeline, text: str, voice: str) -> bytes:
    # Kokoro's generator yields one chunk per sentence/clause; concatenate all of
    # them into a single wav rather than returning only the first chunk, since a
    # multi-sentence reply otherwise plays back truncated.
    chunks = [audio for _graphemes, _phonemes, audio in pipeline(text, voice=voice)]
    if not chunks:
        raise HTTPException(status_code=422, detail="no audio generated for input text")
    combined = np.concatenate(chunks)
    buffer = io.BytesIO()
    sf.write(buffer, combined, SAMPLE_RATE, format="WAV")
    return buffer.getvalue()
