"""Trajectory evals: does the real model's tool-call/event order for a turn match
the intended policy (evaluate before remediating, PII gate before persisting a fact,
etc.)? Glass-box — catches wiring/prompt-policy drift that end-to-end text checks
miss. Run with: pytest evals -m eval -k trajectories
"""

from __future__ import annotations

import pytest

from evals.graders.trajectory import check_excludes, check_subsequence
from evals.harness import (
    build_agent_llm,
    build_real_orchestrator,
    event_type_sequence,
    load_cases,
    run_turn,
    tool_call_sequence,
)

pytestmark = pytest.mark.eval

CASES = load_cases("trajectories.yaml")


@pytest.fixture
def orchestrator():
    llm = build_agent_llm()
    graph, repo, _kg_graph = build_real_orchestrator(llm)
    return graph, repo


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_trajectory(case, orchestrator):
    graph, repo = orchestrator
    final_state = await run_turn(
        graph,
        current_kc=case["current_kc"],
        employee_text=case.get("employee_text", ""),
        question=case.get("question", ""),
        is_session_open=case.get("is_session_open", False),
    )

    tools = tool_call_sequence(final_state)
    events = event_type_sequence(repo, final_state["session_id"])

    if "expect_tools_in_order" in case:
        result = check_subsequence(tools, case["expect_tools_in_order"])
        assert result.passed, result.detail
    if "expect_tools_excludes" in case:
        result = check_excludes(tools, case["expect_tools_excludes"])
        assert result.passed, result.detail
    if "expect_events_in_order" in case:
        result = check_subsequence(events, case["expect_events_in_order"])
        assert result.passed, result.detail
    if "expect_events_excludes" in case:
        result = check_excludes(events, case["expect_events_excludes"])
        assert result.passed, result.detail
