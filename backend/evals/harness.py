"""Shared setup for real-LLM evals: a real orchestrator against the real KG/SOP
corpus and an in-memory `Repo`, plus helpers to read back what actually happened.

Deliberately not shared with `tests/` — those tests stub the LLM boundary so they're
free/deterministic/CI-safe (CLAUDE.md's tier split). Everything here calls a real
provider API (`app/agent/llm.py`'s Anthropic/Gemini/OpenAI implementations), so it's
opt-in only (`pytest evals -m eval`), gated on that provider's key being configured.
`build_agent_llm`/`build_judge_llm` are separate builders (default: gemini, override
with `EVAL_AGENT_PROVIDER`/`EVAL_JUDGE_PROVIDER`) so grading is never done by the same
model instance that produced the output being graded.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.llm import StructuredLLM
from app.agent.orchestrator import build_orchestrator
from app.config import settings
from app.kg.loader import build_digraph, load_kcs
from app.persistence.repo import Repo
from app.rag.retrieve import build_index_from_sops

_BACKEND_DIR = Path(__file__).resolve().parent.parent
KCS_PATH = _BACKEND_DIR / "app" / "kg" / "graph.yaml"
SOPS_DIR = _BACKEND_DIR.parent / "docs" / "sops"

# Which pydantic-settings field holds each provider's key — same source the real
# LLM classes read (.env included), so this can't drift out of sync with what
# actually gets used.
_PROVIDER_KEY_FIELDS = {
    "anthropic": "anthropic_api_key",
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
}


def _build_llm(provider: str) -> StructuredLLM:
    if provider == "anthropic":
        from app.agent.llm import AnthropicLLM

        return AnthropicLLM()
    if provider == "gemini":
        from app.agent.llm import GeminiLLM

        return GeminiLLM()
    if provider == "openai":
        from app.agent.llm import OpenAILLM

        return OpenAILLM()
    raise ValueError(f"unknown eval LLM provider {provider!r}")


def _require_provider_key(provider: str) -> None:
    if not getattr(settings, _PROVIDER_KEY_FIELDS[provider]):
        pytest.skip(f"no {provider} API key configured — skipping real-LLM eval")


def build_agent_llm() -> StructuredLLM:
    """The LLM that plays Sofía for a turn — set `EVAL_AGENT_PROVIDER` to override
    (default: gemini)."""
    provider = os.environ.get("EVAL_AGENT_PROVIDER", "gemini")
    _require_provider_key(provider)
    return _build_llm(provider)


def build_judge_llm() -> StructuredLLM:
    """A separate LLM instance for grading, so a model never grades its own output
    by construction. Set `EVAL_JUDGE_PROVIDER` to override (default: gemini, same as
    the agent default today only because it's the funded provider — swap freely once
    another provider has credit)."""
    provider = os.environ.get("EVAL_JUDGE_PROVIDER", "gemini")
    _require_provider_key(provider)
    return _build_llm(provider)


def build_real_orchestrator(llm: StructuredLLM, *, max_tool_iterations: int = 6):
    """Real orchestrator graph over the committed KG + SOP corpus, with a fresh
    in-memory `Repo` (so evals never touch a real database file)."""
    repo = Repo(":memory:")
    kg_graph = build_digraph(load_kcs(KCS_PATH))
    index = build_index_from_sops(SOPS_DIR)
    graph = build_orchestrator(
        llm=llm,
        index=index,
        repo=repo,
        kg_graph=kg_graph,
        checkpointer=MemorySaver(),
        max_tool_iterations=max_tool_iterations,
    )
    return graph, repo, kg_graph


async def run_turn(
    graph,
    *,
    current_kc: str,
    employee_text: str = "",
    question: str = "",
    is_session_open: bool = False,
    session_id: str | None = None,
    thread_id: str | None = None,
) -> dict:
    """Run one turn against a fresh session/thread. Each eval case gets its own
    session_id/thread_id so events and checkpointed state never bleed across cases."""
    session_id = session_id or f"eval-{uuid4()}"
    thread_id = thread_id or session_id
    config = {"configurable": {"thread_id": thread_id}}
    state = {
        "session_id": session_id,
        "employee_id": f"employee-{session_id}",
        "language": "en",
        "current_kc": current_kc,
        "mastery": {},
        "turn_index": 0,
        "employee_text": employee_text,
        "question": question,
        "is_session_open": is_session_open,
    }
    final_state = await graph.ainvoke(state, config)
    final_state["session_id"] = session_id
    return final_state


def tool_call_sequence(final_state: dict) -> list[str]:
    """Tool names in call order, read from the turn's scratchpad."""
    names: list[str] = []
    for message in final_state.get("scratchpad", []):
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                names.append(call["name"])
    return names


def event_type_sequence(repo: Repo, session_id: str) -> list[str]:
    """Persisted event types in order — the audit trail `replay()` relies on."""
    return [event.event_type for event in repo.list_events(session_id)]


_DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


def load_cases(filename: str) -> list[dict]:
    """A dataset YAML file's top-level list, or the list under a named key for
    files with multiple subsets (e.g. `grounded_cases`/`abstain_cases`)."""
    return yaml.safe_load((_DATASETS_DIR / filename).read_text(encoding="utf-8"))
