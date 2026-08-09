"""Process-wide singletons for the conversation runtime: the KG, the RAG index, the
persistence repo, and the compiled orchestrator graph. Built lazily on first use,
mirroring `app/api/studio.py`'s `get_repo()` pattern — no FastAPI lifespan needed, so
API tests that call the app without `with TestClient(...)` keep working exactly like
the existing chat/studio tests do.

`get_compiled_graph()` returns `None` when the configured provider's API key is
missing; the chat route falls back to `EchoAgent` in that case rather than crash or
silently mock LLM behavior (CLAUDE.md: never a crash).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import networkx as nx

from app.agent.llm import StructuredLLM, StructuredLLMError, get_structured_llm
from app.agent.orchestrator import build_orchestrator
from app.config import settings
from app.kg.loader import build_digraph, load_kcs
from app.persistence.repo import Repo
from app.rag.retrieve import Index, build_index_from_sops

logger = logging.getLogger(__name__)

KG_PATH = Path(__file__).resolve().parents[1] / "kg" / "graph.yaml"
SOPS_DIR = Path(__file__).resolve().parents[3] / "docs" / "sops"

_kg_graph: nx.DiGraph | None = None
_rag_index: Index | None = None
_repo: Repo | None = None
_compiled_graph = None
_checkpointer_cm = None  # kept alive deliberately, see get_compiled_graph()
_graph_lock = asyncio.Lock()


def get_kg_graph() -> nx.DiGraph:
    global _kg_graph
    if _kg_graph is None:
        _kg_graph = build_digraph(load_kcs(KG_PATH))
    return _kg_graph


def get_rag_index() -> Index | None:
    global _rag_index
    if _rag_index is None and SOPS_DIR.is_dir():
        _rag_index = build_index_from_sops(SOPS_DIR)
    return _rag_index


def get_repo() -> Repo:
    global _repo
    if _repo is None:
        _repo = Repo(settings.runtime_db_path)
    return _repo


async def get_compiled_graph():
    """The compiled orchestrator graph. `None` if no API key or no SOP corpus is
    available. Opens the checkpointer's SQLite connection once and keeps it open for
    the process's lifetime — acceptable for this slice's single-process scope
    (CLAUDE.md: "single process; no Kafka"), same non-goal as the rest of the demo."""
    global _compiled_graph, _checkpointer_cm
    if _compiled_graph is not None:
        return _compiled_graph
    required_key = (
        settings.gemini_api_key if settings.llm_provider == "gemini" else settings.anthropic_api_key
    )
    if not required_key:
        return None

    async with _graph_lock:
        if _compiled_graph is not None:
            return _compiled_graph

        rag_index = get_rag_index()
        if rag_index is None:
            logger.warning("docs/sops not found; conversation graph disabled")
            return None

        try:
            llm: StructuredLLM = get_structured_llm()
        except StructuredLLMError as error:
            logger.warning("LLM client unavailable, conversation graph disabled: %s", error)
            return None

        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        # `from_conn_string` is an @asynccontextmanager; entering it manually (instead
        # of `async with ...:`) is what lets the connection outlive this function call
        # for the process's lifetime. The context-manager object itself MUST be kept
        # referenced here — it wraps `async with aiosqlite.connect(...) as conn: yield
        # ...`, so if it were only a local variable, it becomes unreferenced the
        # moment this function returns and Python's GC finalizes the abandoned
        # generator, which runs `aiosqlite`'s `__aexit__` and closes the connection
        # out from under the running server (surfaces as "Cannot operate on a closed
        # database" on the next checkpoint read/write, sometimes seconds later).
        _checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path))
        saver = await _checkpointer_cm.__aenter__()

        _compiled_graph = build_orchestrator(
            llm=llm,
            index=rag_index,
            repo=get_repo(),
            kg_graph=get_kg_graph(),
            mastery_threshold=settings.mastery_threshold,
            checkpointer=saver,
        )
        return _compiled_graph
