"""Chat API (plan §5). `/chat` streams one graph turn per request over SSE, keyed by
`session_id` (the graph's `thread_id`) so a client can resume a session across
requests just by echoing the id back. Falls back to the pre-existing `EchoAgent` when
the configured provider's API key is missing (`runtime.get_compiled_graph()` returns
`None`) rather than error out — keeps the UI demoable with zero setup.

`GET /session/{id}/mastery` and `/facts` read the graph's own checkpointed state as
the source of truth (no separate session table — the checkpointer already persists
it); `DELETE /facts/{id}` is the employee view/delete right (PRD §7).
"""

import base64
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent import runtime
from app.agent.base import get_agent
from app.agent.tts import synthesize
from app.config import settings
from app.kg.loader import next_assessable_kc, unlocked_kcs
from app.persistence.repo import FactNotFoundError
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(request: ChatRequest) -> EventSourceResponse:
    compiled_graph = await runtime.get_compiled_graph()
    if compiled_graph is None:
        return EventSourceResponse(_echo_stream(request))
    return EventSourceResponse(_graph_stream(request, compiled_graph))


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# --- panel data (plan §5) ----------------------------------------------------


class KCInfo(BaseModel):
    id: str
    name: str
    domain: str
    description: str
    prerequisites: list[str]
    gated: bool
    mastery: float | None = None


@router.get("/kg", response_model=list[KCInfo])
async def get_kg(session_id: str | None = None) -> list[KCInfo]:
    """KC metadata + gating state for the mastery panel. `session_id` scopes gating
    to that session's mastery; omit it to see the graph fully locked (mastery={})."""
    kg_graph = runtime.get_kg_graph()
    mastery: dict[str, float] = {}
    if session_id:
        mastery = await _session_mastery(session_id)

    threshold = settings.mastery_threshold
    unlocked = unlocked_kcs(kg_graph, mastery, threshold)
    infos = []
    for kc_id in kg_graph.nodes:
        kc = kg_graph.nodes[kc_id]["kc"]
        infos.append(
            KCInfo(
                id=kc.id,
                name=kc.name,
                domain=kc.domain,
                description=kc.description,
                prerequisites=kc.prerequisites,
                gated=kc_id not in unlocked,
                mastery=mastery.get(kc_id),
            )
        )
    return sorted(infos, key=lambda info: info.id)


@router.get("/session/{session_id}/mastery")
async def get_session_mastery(session_id: str) -> dict[str, float]:
    return await _session_mastery(session_id, required=True)


@router.get("/session/{session_id}/facts")
async def get_session_facts(session_id: str) -> list[dict]:
    employee_id = await _session_employee_id(session_id)
    repo = runtime.get_repo()
    return [stored.model_dump() for stored in repo.list_facts(employee_id)]


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: int) -> dict[str, int]:
    """PRD §7: the employee's right to delete what Sofía remembers about them."""
    repo = runtime.get_repo()
    try:
        repo.delete_fact(fact_id)
    except FactNotFoundError as error:
        raise HTTPException(status_code=404, detail=f"fact '{fact_id}' not found") from error
    return {"deleted": fact_id}


# --- echo fallback (no API key configured) ------------------------------------


async def _echo_stream(request: ChatRequest) -> AsyncIterator[dict]:
    agent = get_agent()
    async for chunk in agent.stream_reply(request.messages):
        yield {"event": "token", "data": chunk}
    yield {"event": "done", "data": ""}


# --- real graph streaming ------------------------------------------------------


async def _graph_stream(request: ChatRequest, compiled_graph) -> AsyncIterator[dict]:
    kg_graph = runtime.get_kg_graph()
    session_id = request.session_id or uuid.uuid4().hex
    employee_text = request.messages[-1].content if request.messages else ""
    config = {"configurable": {"thread_id": session_id}}

    yield {"event": "session", "data": json.dumps({"session_id": session_id})}

    snapshot = await compiled_graph.aget_state(config)
    if snapshot.values:
        if request.is_session_open:
            logger.warning("session=%s is_session_open on a resumed session, ignoring", session_id)
        current_kc = snapshot.values["current_kc"]
        payload: dict = {
            "employee_text": employee_text,
            "question": _question_for(kg_graph, current_kc),
            "is_session_open": False,
        }
    else:
        threshold = settings.mastery_threshold
        mastery = runtime.get_repo().get_mastery(request.employee_id)
        current_kc = next_assessable_kc(kg_graph, mastery, threshold) or next(iter(kg_graph.nodes))
        payload = {
            "session_id": session_id,
            "employee_id": request.employee_id,
            "channel": request.channel,
            "language": request.language,
            "messages": [],
            "current_kc": current_kc,
            "mastery": mastery,
            "turn_index": 0,
            "pending_facts": [],
            "citations": [],
            "employee_text": employee_text,
            "question": _question_for(kg_graph, current_kc),
            "is_session_open": request.is_session_open,
        }

    finalized_text = ""
    try:
        async for step in compiled_graph.astream(payload, config, stream_mode="updates"):
            for node_name, update in step.items():
                for event in _events_for_step(node_name, update):
                    if event["event"] == "token":
                        finalized_text += event["data"]
                    yield event
    except Exception:
        # Once SSE headers are sent, FastAPI's exception handlers can no longer turn
        # a mid-stream crash into an HTTP error response — this is the only remaining
        # boundary that can tell the client anything went wrong instead of the
        # connection just going silent. LLM-boundary failures are already handled
        # with safe fallbacks inside the graph nodes themselves (never raise here);
        # what reaches this point is unexpected (DB, checkpointer, programming
        # errors) — log it with full context, tell the client without leaking detail.
        logger.exception("graph turn crashed for session %s", session_id)
        yield {
            "event": "error",
            "data": json.dumps({"message": "Sofía couldn't process that turn. Please try again."}),
        }
        finalized_text = ""

    if finalized_text:
        audio_bytes = await synthesize(finalized_text)
        if audio_bytes:
            yield {
                "event": "audio",
                "data": json.dumps({"audio_b64": base64.b64encode(audio_bytes).decode()}),
            }

    yield {"event": "done", "data": ""}


def _events_for_step(node_name: str, update: dict | None) -> Iterator[dict]:
    """Derive SSE events from an orchestrator step. Each key only appears in a
    `tools` update on the specific loop iteration that changed it (LangGraph's
    default `LastValue` channel keeps a field's prior value when a node doesn't
    return it), so these checks fire exactly once per turn, not once per iteration."""
    if not update:
        return
    if node_name == "tools":
        if update.get("last_evaluation"):
            yield {
                "event": "reasoning",
                "data": json.dumps({"tool_call": "assess_reply", **update["last_evaluation"]}),
            }
        if update.get("mastery"):
            yield {"event": "mastery_update", "data": json.dumps(update["mastery"])}
        for citation in update.get("citations", []):
            yield {"event": "citation", "data": json.dumps(citation)}
        for fact in update.get("pending_facts", []):
            yield {"event": "memory_event", "data": json.dumps(fact)}
        if update.get("ended"):
            yield {"event": "session_stop", "data": ""}
    elif node_name == "finalize":
        for message in update.get("messages", []):
            yield {"event": "token", "data": message["content"]}


def _question_for(kg_graph, kc_id: str) -> str:
    return kg_graph.nodes[kc_id]["kc"].description


async def _session_mastery(session_id: str, *, required: bool = False) -> dict[str, float]:
    compiled_graph = await runtime.get_compiled_graph()
    if compiled_graph is None:
        if required:
            raise HTTPException(status_code=503, detail="conversation graph unavailable")
        return {}
    snapshot = await compiled_graph.aget_state({"configurable": {"thread_id": session_id}})
    if required and not snapshot.values:
        raise HTTPException(status_code=404, detail=f"session '{session_id}' not found")
    return snapshot.values.get("mastery", {})


async def _session_employee_id(session_id: str) -> str:
    compiled_graph = await runtime.get_compiled_graph()
    if compiled_graph is None:
        raise HTTPException(status_code=503, detail="conversation graph unavailable")
    snapshot = await compiled_graph.aget_state({"configurable": {"thread_id": session_id}})
    if not snapshot.values:
        raise HTTPException(status_code=404, detail=f"session '{session_id}' not found")
    return snapshot.values["employee_id"]
