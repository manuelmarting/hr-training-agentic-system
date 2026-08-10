"""Client for the standalone Kokoro TTS voice-service (voice-service/). Best-effort
side output of a chat turn: any failure (unreachable, slow, non-2xx) degrades to
`None` rather than raising, so a TTS outage never breaks the deterministic
text-only conversation flow — see app/api/chat.py's use of `synthesize()`.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# The voice-service only ships English and Spanish Kokoro pipelines. Anything else
# (e.g. SessionState's "ro") falls back to English rather than a language kokoro
# can't phonemize correctly.
_SUPPORTED_LANGUAGES = {"en", "es"}


async def synthesize(text: str, language: str = "en") -> bytes | None:
    if not text.strip():
        return None
    voice_language = language if language in _SUPPORTED_LANGUAGES else "en"
    try:
        async with httpx.AsyncClient(timeout=settings.kokoro_timeout_s) as client:
            response = await client.post(
                f"{settings.kokoro_service_url}/synthesize",
                json={"text": text, "language": voice_language},
            )
            response.raise_for_status()
            return response.content
    except httpx.HTTPError:
        logger.warning("voice synthesis unavailable, continuing text-only", exc_info=True)
        return None
