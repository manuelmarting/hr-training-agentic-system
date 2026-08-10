"""Chat API tests for the real-orchestrator path: session bootstrap/continuity, the
SSE event vocabulary, and the panel-data endpoints. The LLM boundary is stubbed and
wired in through `app.agent.runtime`'s module-level singletons via monkeypatch — no
network, no API key. `tests/test_chat.py` covers the no-API-key `EchoAgent` fallback
path separately.
"""

import base64
import json
from pathlib import Path

import pytest
import sse_starlette.sse
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent import runtime
from app.agent.orchestrator import build_orchestrator
from app.agent.tools.deliver_reply import DeliveryMessage
from app.api import chat as chat_api
from app.kg.loader import build_digraph, load_kcs
from app.main import app
from app.persistence.repo import Repo
from app.rag.retrieve import build_index_from_sops
from app.schemas.extraction import TurnEvaluation

GRAPH_PATH = Path(__file__).parent.parent / "app" / "kg" / "graph.yaml"
SOPS_DIR = Path(__file__).parent.parent.parent / "docs" / "sops"
_FAKE_AUDIO = b"RIFF....WAVEfmt fake audio bytes"


class ScriptedLLM:
    """Scripts both grading (`extract`) and the orchestrator's own tool-selection
    loop (`acall_with_tools`) with the same assess -> compose policy
    `ORCHESTRATOR_SYSTEM_PROMPT` asks a real model to follow."""

    def __init__(self, classifications: list[str]) -> None:
        self._classifications = list(classifications)
        self.calls = 0

    async def extract(self, output_model, system, user):
        name = getattr(output_model, "__name__", "")
        if output_model is TurnEvaluation:
            classification = self._classifications[self.calls]
            self.calls += 1
            return TurnEvaluation(
                kc_id="unused-overridden-by-caller",
                classification=classification,
                confidence=0.8,
                language="en",
                sentiment="neutral",
            )
        if name == "_FactExtraction":
            return output_model(fact=None)
        if name == "_SpecialCategoryCheck":
            return output_model(safe=True)
        if output_model is DeliveryMessage:
            return DeliveryMessage(text="(stub) let's continue")
        raise AssertionError(f"unexpected output_model {output_model}")

    async def acall_with_tools(self, messages, tools):
        ai_tool_calls = [
            call["name"]
            for m in messages
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for call in m.tool_calls
        ]
        last_tool = ai_tool_calls[-1] if ai_tool_calls else None
        tool_results = [m.content for m in messages if isinstance(m, ToolMessage)]
        call_id = f"call-{len(tool_results)}"

        def _call(name: str) -> AIMessage:
            return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": call_id}])

        if last_tool is None:
            return _call("evaluate_response")
        if last_tool == "evaluate_response":
            return _call("deliver_reply")
        return AIMessage(content="done")


class CrashingLLM:
    """Simulates an unexpected (non-`StructuredLLMError`) exception, e.g. a bug or an
    infra failure below the LLM boundary that the graph nodes don't already catch —
    `StructuredLLMError` itself is already swallowed with a safe fallback inside
    `evaluate_turn`/`extract_and_gate_fact`, so it never reaches the SSE layer."""

    async def extract(self, output_model, system, user):
        raise RuntimeError("simulated unexpected crash")

    async def acall_with_tools(self, messages, tools):
        raise RuntimeError("simulated unexpected crash")


def _async_return(value):
    async def _get():
        return value

    return _get


_shared_client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_sse_shutdown_event():
    """`sse_starlette.sse.AppStatus.should_exit_event` is a module-level singleton
    bound to whichever event loop first awaited it. TestClient's `.stream()` spins a
    fresh anyio portal/event loop per call, so a second SSE request in this test
    module trips "Event object is bound to a different event loop" unless the
    singleton is cleared beforehand so it gets recreated on the current loop."""
    sse_starlette.sse.AppStatus.should_exit_event = None
    yield


@pytest.fixture
def graph_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    if not SOPS_DIR.is_dir():
        pytest.skip(f"docs/sops not found at {SOPS_DIR}")

    kg_graph = build_digraph(load_kcs(GRAPH_PATH))
    rag_index = build_index_from_sops(SOPS_DIR)
    repo = Repo(":memory:")
    llm = ScriptedLLM(["correct", "correct", "correct"])
    compiled = build_orchestrator(
        llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph, checkpointer=MemorySaver()
    )

    monkeypatch.setattr(runtime, "get_compiled_graph", _async_return(compiled))
    monkeypatch.setattr(runtime, "get_kg_graph", lambda: kg_graph)
    monkeypatch.setattr(runtime, "get_repo", lambda: repo)

    # Reuse one TestClient/anyio portal across tests in this module: sse_starlette
    # keeps a module-level shutdown Event tied to whichever event loop first created
    # it, so spinning up a fresh TestClient (and thus a fresh loop) per test trips
    # "Event object is bound to a different event loop" on the second stream call.
    return _shared_client


@pytest.fixture
def graph_client_crashing_llm(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    if not SOPS_DIR.is_dir():
        pytest.skip(f"docs/sops not found at {SOPS_DIR}")

    kg_graph = build_digraph(load_kcs(GRAPH_PATH))
    rag_index = build_index_from_sops(SOPS_DIR)
    repo = Repo(":memory:")
    compiled = build_orchestrator(
        llm=CrashingLLM(), index=rag_index, repo=repo, kg_graph=kg_graph, checkpointer=MemorySaver()
    )

    monkeypatch.setattr(runtime, "get_compiled_graph", _async_return(compiled))
    monkeypatch.setattr(runtime, "get_kg_graph", lambda: kg_graph)
    monkeypatch.setattr(runtime, "get_repo", lambda: repo)

    return _shared_client


def _parse_sse(body: str) -> list[tuple[str | None, str]]:
    events: list[tuple[str | None, str]] = []
    event_name: str | None = None
    for line in body.splitlines():
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            events.append((event_name, line.removeprefix("data:").strip()))
    return events


def _post_turn(client: TestClient, text: str, session_id: str | None = None) -> str:
    sse_starlette.sse.AppStatus.should_exit_event = None  # see _reset_sse_shutdown_event
    body = {"messages": [{"role": "user", "content": text}]}
    if session_id is not None:
        body["session_id"] = session_id
    with client.stream("POST", "/api/chat", json=body) as response:
        assert response.status_code == 200
        return "".join(response.iter_text())


def _post_session_open(client: TestClient) -> str:
    sse_starlette.sse.AppStatus.should_exit_event = None  # see _reset_sse_shutdown_event
    body = {"messages": [], "is_session_open": True}
    with client.stream("POST", "/api/chat", json=body) as response:
        assert response.status_code == 200
        return "".join(response.iter_text())


# --- SSE event vocabulary ------------------------------------------------------


def test_new_session_streams_expected_events(graph_client: TestClient):
    events = _parse_sse(_post_turn(graph_client, "gloves"))
    names = [name for name, _ in events]

    assert names[0] == "session"
    assert "reasoning" in names
    assert "trace_step" in names
    assert "mastery_update" in names
    assert "token" in names
    assert names[-1] == "done"

    session_payload = json.loads(next(data for name, data in events if name == "session"))
    assert session_payload["session_id"]

    reasoning_payload = json.loads(next(data for name, data in events if name == "reasoning"))
    assert reasoning_payload["tool_call"] == "evaluate_response"

    trace_payloads = [json.loads(data) for name, data in events if name == "trace_step"]
    tools_called = [step["tool"] for step in trace_payloads if step["type"] == "tool_call"]
    # ScriptedLLM's policy for this turn: grade, then compose the reply -- in order,
    # and every tool call shows up here, not just evaluate_response.
    assert tools_called == ["evaluate_response", "deliver_reply"]


def test_session_open_streams_welcome_without_grading(graph_client: TestClient):
    events = _parse_sse(_post_session_open(graph_client))
    names = [name for name, _ in events]

    assert names[0] == "session"
    assert "token" in names
    assert "reasoning" not in names
    assert "mastery_update" not in names
    assert names[-1] == "done"

    # ScriptedLLM still attempts evaluate_response first (it only reacts to what
    # the prior tool call *was*, not whether it succeeded) -- tools_node's
    # is_session_open guard rejects it with an error result, which still shows up
    # in the trace, then the model moves on to deliver_reply.
    trace_payloads = [json.loads(data) for name, data in events if name == "trace_step"]
    tools_called = [step["tool"] for step in trace_payloads if step["type"] == "tool_call"]
    assert tools_called == ["evaluate_response", "deliver_reply"]
    rejected = next(step for step in trace_payloads if step.get("tool") == "evaluate_response")
    assert rejected["result"].startswith("error:")


def test_session_open_ignored_on_resumed_session(graph_client: TestClient):
    events1 = _parse_sse(_post_turn(graph_client, "gloves"))
    session_id = json.loads(next(data for name, data in events1 if name == "session"))["session_id"]

    body = {"messages": [], "session_id": session_id, "is_session_open": True}
    sse_starlette.sse.AppStatus.should_exit_event = None
    with graph_client.stream("POST", "/api/chat", json=body) as response:
        assert response.status_code == 200
        events2 = _parse_sse("".join(response.iter_text()))

    session_id_2 = json.loads(next(data for name, data in events2 if name == "session"))[
        "session_id"
    ]
    assert session_id_2 == session_id


def test_unexpected_crash_streams_error_event_and_still_closes(
    graph_client_crashing_llm: TestClient,
):
    events = _parse_sse(_post_turn(graph_client_crashing_llm, "gloves"))
    names = [name for name, _ in events]

    assert names[0] == "session"
    assert "error" in names
    assert names[-1] == "done"
    assert "token" not in names

    error_payload = json.loads(next(data for name, data in events if name == "error"))
    assert error_payload["message"]


def test_session_id_is_stable_across_turns(graph_client: TestClient):
    events1 = _parse_sse(_post_turn(graph_client, "gloves"))
    session_id = json.loads(next(data for name, data in events1 if name == "session"))["session_id"]

    events2 = _parse_sse(_post_turn(graph_client, "more", session_id=session_id))
    session_id_2 = json.loads(next(data for name, data in events2 if name == "session"))[
        "session_id"
    ]

    assert session_id_2 == session_id


# --- voice output (Kokoro TTS, best-effort side output of a turn) --------------


def test_turn_streams_audio_event_when_voice_service_available(
    graph_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    async def _fake_synthesize(text: str, language: str = "en") -> bytes:
        assert text  # the finalized reply text, not empty
        return _FAKE_AUDIO

    monkeypatch.setattr(chat_api, "synthesize", _fake_synthesize)

    events = _parse_sse(_post_turn(graph_client, "gloves"))
    names = [name for name, _ in events]

    assert "audio" in names
    audio_payload = json.loads(next(data for name, data in events if name == "audio"))
    assert base64.b64decode(audio_payload["audio_b64"]) == _FAKE_AUDIO
    assert names[-1] == "done"


def test_turn_completes_without_audio_event_when_voice_service_unavailable(
    graph_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    async def _unavailable_synthesize(text: str, language: str = "en") -> None:
        return None

    monkeypatch.setattr(chat_api, "synthesize", _unavailable_synthesize)

    events = _parse_sse(_post_turn(graph_client, "gloves"))
    names = [name for name, _ in events]

    assert "audio" not in names
    assert "token" in names
    assert names[-1] == "done"


# --- panel data endpoints ------------------------------------------------------


def test_kg_endpoint_lists_kcs_with_gating(graph_client: TestClient):
    response = graph_client.get("/api/kg")
    assert response.status_code == 200
    kcs = response.json()

    ids = {kc["id"] for kc in kcs}
    assert "SAF.001" in ids and "SAF.003" in ids

    unlocked_no_prereqs = next(kc for kc in kcs if kc["id"] == "SAF.001")
    assert unlocked_no_prereqs["gated"] is False

    gated_by_chain = next(kc for kc in kcs if kc["id"] == "SAF.003")
    assert gated_by_chain["gated"] is True  # SAF.002 not mastered


def test_session_mastery_and_facts_endpoints(graph_client: TestClient):
    events = _parse_sse(_post_turn(graph_client, "gloves"))
    session_id = json.loads(next(data for name, data in events if name == "session"))["session_id"]

    mastery_response = graph_client.get(f"/api/session/{session_id}/mastery")
    assert mastery_response.status_code == 200
    assert mastery_response.json()  # at least one KC now has a mastery entry

    facts_response = graph_client.get(f"/api/session/{session_id}/facts")
    assert facts_response.status_code == 200
    assert facts_response.json() == []  # ScriptedLLM never extracts a fact


def test_unknown_session_mastery_returns_404(graph_client: TestClient):
    response = graph_client.get("/api/session/does-not-exist/mastery")
    assert response.status_code == 404


def test_delete_unknown_fact_returns_404(graph_client: TestClient):
    response = graph_client.delete("/api/facts/999")
    assert response.status_code == 404
