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
from kokoro import KModel, KPipeline
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000

# One KPipeline per supported language, sharing a single KModel (kokoro's own
# recommendation — see KPipeline's docstring). Kokoro's G2P is language-aware, so a
# pipeline built for lang_code="a" (English) mispronounces Spanish text; each
# language needs its own pipeline plus a matching default voice.
_PIPELINE_CONFIG: dict[str, dict[str, str]] = {
    "en": {"lang_code": "a", "default_voice": "af_heart"},
    "es": {"lang_code": "e", "default_voice": "ef_dora"},
}
_pipelines: dict[str, KPipeline] = {}
_state: Literal["initializing", "ready", "error"] = "initializing"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _state
    try:
        loop = asyncio.get_event_loop()

        def _build_pipelines() -> dict[str, KPipeline]:
            model = KModel()
            return {
                language: KPipeline(lang_code=cfg["lang_code"], model=model)
                for language, cfg in _PIPELINE_CONFIG.items()
            }

        _pipelines.update(await loop.run_in_executor(None, _build_pipelines))
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
    language: Literal["en", "es"] = "en"
    voice: str | None = None


@app.post("/synthesize")
async def synthesize(request: SynthesizeRequest) -> Response:
    pipeline = _pipelines.get(request.language)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="model not ready")

    voice = request.voice or _PIPELINE_CONFIG[request.language]["default_voice"]
    loop = asyncio.get_event_loop()
    audio_bytes = await loop.run_in_executor(None, lambda: _generate(pipeline, request.text, voice))
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
