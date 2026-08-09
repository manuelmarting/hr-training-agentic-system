"""Client for the standalone Kokoro TTS voice-service (voice-service/). Best-effort
side output of a chat turn: any failure (unreachable, slow, non-2xx) degrades to
`None` rather than raising, so a TTS outage never breaks the deterministic
text-only conversation flow — see app/api/chat.py's use of `synthesize()`.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def synthesize(text: str) -> bytes | None:
    if not text.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=settings.kokoro_timeout_s) as client:
            response = await client.post(
                f"{settings.kokoro_service_url}/synthesize", json={"text": text}
            )
            response.raise_for_status()
            return response.content
    except httpx.HTTPError:
        logger.warning("voice synthesis unavailable, continuing text-only", exc_info=True)
        return None
