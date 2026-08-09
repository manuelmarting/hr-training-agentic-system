import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.logging import DefaultFormatter

from app.api.chat import router as chat_router
from app.api.studio import router as studio_router
from app.config import settings

logger = logging.getLogger(__name__)

# No prior logging config existed — INFO-level app logs (request/agent-action logging,
# CLAUDE.md's auditability requirement) would otherwise be dropped by the default root
# level (WARNING). Reuses uvicorn's own formatter so app logs read like its "INFO:  ..."
# lines instead of a different style; scoped to "app" so third-party libraries are
# unaffected.
_handler = logging.StreamHandler()
_handler.setFormatter(DefaultFormatter(fmt="%(levelprefix)s %(name)s - %(message)s"))
app_logger = logging.getLogger("app")
app_logger.addHandler(_handler)
app_logger.setLevel(logging.INFO)
app_logger.propagate = False

app = FastAPI(title="HR Training Agentic System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One INFO line per request (CLAUDE.md: log with context for auditability).
    SSE responses (`/api/chat`) log on stream open, not close — the duration here
    reflects time-to-first-byte, not the full stream lifetime."""
    started = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - started) * 1000
    logger.info(
        "request method=%s path=%s status=%d duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.include_router(chat_router)
app.include_router(studio_router)

static_dir = Path(__file__).parent / "static"
_index = static_dir / "index.html"

# SPA client-side routes (App.tsx switches on pathname). StaticFiles(html=True) only
# serves index.html at the root, so deep links like /studio need an explicit fallback.
if _index.exists():

    @app.get("/studio", include_in_schema=False)
    @app.get("/studio/{_path:path}", include_in_schema=False)
    async def studio_spa(_path: str = "") -> FileResponse:
        return FileResponse(_index)


if static_dir.exists() and any(static_dir.iterdir()):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
