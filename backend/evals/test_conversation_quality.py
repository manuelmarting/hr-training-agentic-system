"""General LLM-as-judge evals for conversation quality: does the real turn's
rendered reply read the way a frontline employee would expect, and does it
correctly reflect the grading outcome for that turn? Run with:
pytest evals -m eval -k conversation_quality
"""

from __future__ import annotations

import pytest

from evals.graders.judge import PASS_THRESHOLD, judge_conversation_quality
from evals.harness import (
    build_agent_llm,
    build_judge_llm,
    build_real_orchestrator,
    load_cases,
    run_turn,
)

pytestmark = pytest.mark.eval

CASES = load_cases("conversation_quality.yaml")


@pytest.fixture
def orchestrator():
    agent_llm = build_agent_llm()
    graph, repo, _kg_graph = build_real_orchestrator(agent_llm)
    judge_llm = build_judge_llm()
    return graph, repo, judge_llm


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_conversation_quality(case, orchestrator):
    graph, repo, judge_llm = orchestrator
    final_state = await run_turn(
        graph,
        current_kc=case["current_kc"],
        employee_text=case["employee_text"],
        question=case["question"],
    )

    events = repo.list_events(final_state["session_id"])
    classification = next(
        (e.payload["classification"] for e in events if e.event_type == "turn_evaluated"), "unknown"
    )
    remediation_happened = any(e.event_type == "remediation" for e in events)
    rendered_reply = final_state["messages"][-1]["content"]

    verdict = await judge_conversation_quality(
        judge_llm,
        rendered_reply=rendered_reply,
        classification=classification,
        remediation_happened=remediation_happened,
    )

    failures = [
        f"{dim}={score} (< {PASS_THRESHOLD})"
        for dim, score in (
            ("tone", verdict.tone_score),
            ("educational_accuracy", verdict.educational_accuracy_score),
            ("appropriateness", verdict.appropriateness_score),
        )
        if score < PASS_THRESHOLD
    ]
    assert not failures, (
        f"{case['id']}: below threshold on {failures} — {verdict.reasoning}\n"
        f"reply: {rendered_reply!r}"
    )
