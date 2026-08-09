"""Orchestrator wiring, resume, and session-close tests.

`ScriptedOrchestratorLLM` below stands in for a real model's tool-selection
decisions with a small deterministic state machine that mirrors
`ORCHESTRATOR_SYSTEM_PROMPT`'s policy (assess -> remediate-if-wrong -> compose, or
assess -> end on opt-out). `assess_reply` folds what used to be three separate tools
(grade/update-mastery/select-next-kc) into one call, so there's no longer an
intermediate "did it update mastery" state to script around. That's intentional and a
real limitation of these tests: they exercise the tool-dispatch plumbing and prove
it's *capable* of reproducing the old fixed-graph behavior when the policy is
followed, not that a real model reliably follows it every turn — CLAUDE.md now
documents that gap explicitly rather than letting a passing test imply otherwise.

The LLM boundary is stubbed — no network, no API key.
"""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.orchestrator import (
    _apply_mastery_update,
    _select_delivery_inputs,
    _session_progress,
    build_orchestrator,
    close_session,
)
from app.agent.subagents.delivery import ABSTAIN_TEXT, DeliveryMessage
from app.kg.loader import (
    DEFAULT_MASTERY_THRESHOLD,
    KnowledgeComponent,
    build_digraph,
    load_kcs,
    next_assessable_kc,
)
from app.mastery import bkt
from app.persistence.repo import Repo
from app.rag.retrieve import Citation, build_index_from_sops
from app.schemas.extraction import TurnEvaluation

_TEST_KC = KnowledgeComponent(
    id="SAF.001",
    name="Test KC",
    domain="safety",
    description="how to test knowledge components",
)


def _evaluation(kc_id: str, classification: str) -> TurnEvaluation:
    return TurnEvaluation(
        kc_id=kc_id,
        classification=classification,
        confidence=0.9,
        language="en",
        sentiment="neutral",
    )


def test_apply_mastery_update_computes_bkt_posterior(kg_graph):
    evaluation = _evaluation("SAF.001", "correct")
    result = _apply_mastery_update(
        {}, evaluation, kg_graph, DEFAULT_MASTERY_THRESHOLD, fallback_kc="SAF.001"
    )
    assert result.prior == bkt.DEFAULT_PARAMS.p_init
    assert result.posterior == bkt.update(bkt.DEFAULT_PARAMS.p_init, "correct")
    assert result.mastery["SAF.001"] == result.posterior


def test_apply_mastery_update_advances_to_lowest_id_unmastered_unlocked_kc(kg_graph):
    """`current_kc` matches what `next_assessable_kc` itself would pick from the
    resulting mastery dict — not necessarily the KC just graded, since a
    lower-id, already-unlocked KC can still be the next one up."""
    evaluation = _evaluation("SAF.001", "incorrect")
    result = _apply_mastery_update(
        {}, evaluation, kg_graph, DEFAULT_MASTERY_THRESHOLD, fallback_kc="SAF.001"
    )
    assert result.posterior < DEFAULT_MASTERY_THRESHOLD
    expected_kc = next_assessable_kc(kg_graph, result.mastery, DEFAULT_MASTERY_THRESHOLD)
    assert result.current_kc == expected_kc


def test_apply_mastery_update_falls_back_when_no_kc_is_assessable(kg_graph):
    """An impossible-to-clear threshold makes `next_assessable_kc` return `None`
    (no unlocked KC is below threshold) — the caller's `fallback_kc` is used."""
    evaluation = _evaluation("SAF.001", "correct")
    result = _apply_mastery_update({}, evaluation, kg_graph, -1.0, fallback_kc="SAF.001")
    assert result.current_kc == "SAF.001"


def test_select_delivery_inputs_cited_remediation_takes_priority():
    last_remediation = {
        "excerpt": "wear gloves at all times",
        "citation": {"doc_id": "03-ppt-operation", "heading": "PPE"},
    }
    inputs = _select_delivery_inputs(
        kc=_TEST_KC, last_remediation=last_remediation, closing=False, session_progress=None
    )
    assert inputs.excerpt == "wear gloves at all times"
    assert inputs.citation == Citation(doc_id="03-ppt-operation", heading="PPE")
    assert inputs.abstain_reason is None
    assert inputs.next_kc_description is None
    assert "wear gloves at all times" in inputs.fallback_text


def test_select_delivery_inputs_abstained_remediation():
    last_remediation = {"knowledge_gap_reason": "no matching SOP section"}
    inputs = _select_delivery_inputs(
        kc=_TEST_KC, last_remediation=last_remediation, closing=False, session_progress=None
    )
    assert inputs.excerpt is None
    assert inputs.citation is None
    assert inputs.abstain_reason == "no matching SOP section"
    assert inputs.next_kc_description is None
    assert inputs.fallback_text == ABSTAIN_TEXT


def test_select_delivery_inputs_no_remediation_not_closing():
    inputs = _select_delivery_inputs(
        kc=_TEST_KC, last_remediation=None, closing=False, session_progress=None
    )
    assert inputs.next_kc_description == _TEST_KC.description
    assert inputs.fallback_text == f"Next: {_TEST_KC.description}"


def test_select_delivery_inputs_closing_without_remediation():
    inputs = _select_delivery_inputs(
        kc=_TEST_KC, last_remediation=None, closing=True, session_progress="2 asked"
    )
    assert inputs.next_kc_description is None
    assert inputs.fallback_text == "That's all for today — thanks for practicing!"
    assert inputs.session_progress == "2 asked"


def test_select_delivery_inputs_closing_with_remediation_keeps_remediation_content():
    """A wrap-up turn that also remediated a knowledge gap this turn should still
    surface that content, not the generic "that's all for today" fallback."""
    last_remediation = {
        "excerpt": "wear gloves at all times",
        "citation": {"doc_id": "03-ppt-operation", "heading": "PPE"},
    }
    inputs = _select_delivery_inputs(
        kc=_TEST_KC, last_remediation=last_remediation, closing=True, session_progress="2 asked"
    )
    assert inputs.next_kc_description is None
    assert "wear gloves at all times" in inputs.fallback_text
    assert inputs.session_progress == "2 asked"


GRAPH_PATH = Path(__file__).parent.parent / "app" / "kg" / "graph.yaml"
SOPS_DIR = Path(__file__).parent.parent.parent / "docs" / "sops"


class ScriptedOrchestratorLLM:
    """Implements both `StructuredLLM` (grading/memory/delivery extraction) and
    `ToolCallingLLM` (the orchestrator's own tool-selection loop)."""

    def __init__(self, classifications: list[str], kc_id: str = "SAF.001") -> None:
        self._classifications = list(classifications)
        self._kc_id = kc_id
        self.grade_calls = 0

    async def extract(self, output_model, system, user):
        name = getattr(output_model, "__name__", "")
        if output_model is TurnEvaluation:
            classification = self._classifications[self.grade_calls]
            self.grade_calls += 1
            return TurnEvaluation(
                kc_id=self._kc_id,
                classification=classification,
                confidence=0.8,
                language="en",
                sentiment="neutral",
                opt_out=classification == "off_topic" and "not now" in user.lower(),
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

        def _call(name: str, args: dict | None = None) -> AIMessage:
            call = {"name": name, "args": args or {}, "id": call_id}
            return AIMessage(content="", tool_calls=[call])

        if last_tool is None:
            return _call("assess_reply")

        if last_tool == "assess_reply":
            last_result = tool_results[-1]
            if "opt_out=True" in last_result:
                return _call("end_session")
            if "classification=off_topic" in last_result:
                return _call("compose_delivery")
            classification = self._classifications[self.grade_calls - 1]
            if classification in ("incorrect", "partial"):
                return _call("remediate", {"reason": "misconception"})
            return _call("compose_delivery")

        if last_tool == "remediate":
            return _call("compose_delivery")

        if last_tool in ("compose_delivery", "end_session"):
            return AIMessage(content="done")

        raise AssertionError(f"unscripted state after tool {last_tool!r}")


@pytest.fixture(scope="module")
def kg_graph():
    return build_digraph(load_kcs(GRAPH_PATH))


@pytest.fixture(scope="module")
def rag_index():
    if not SOPS_DIR.is_dir():
        pytest.skip(f"docs/sops not found at {SOPS_DIR}")
    return build_index_from_sops(SOPS_DIR)


def _initial_state(session_id: str, employee_id: str = "emp-1") -> dict:
    return {
        "session_id": session_id,
        "employee_id": employee_id,
        "channel": "telegram",
        "language": "en",
        "messages": [],
        "current_kc": "SAF.001",
        "mastery": {},
        "turn_index": 0,
        "pending_facts": [],
        "citations": [],
    }


async def _run_turn(
    graph, config, employee_text, question="What PPE?", *, initial: dict | None = None
):
    payload = {"employee_text": employee_text, "question": question}
    if initial is not None:
        payload = {**initial, **payload}
    return await graph.ainvoke(payload, config)


# --- single-turn wiring -------------------------------------------------------


async def test_correct_answer_updates_mastery_and_advances(kg_graph, rag_index):
    repo = Repo(":memory:")
    llm = ScriptedOrchestratorLLM(["correct"])
    graph = build_orchestrator(llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph)
    config = {"configurable": {"thread_id": "sess-single"}}

    result = await _run_turn(graph, config, "gloves", initial=_initial_state("sess-single"))

    assert result["mastery"]["SAF.001"] > 0.3
    assert result["turn_index"] == 1
    assert result["messages"][-1]["role"] == "assistant"
    events = repo.list_events("sess-single")
    assert [e.event_type for e in events] == ["turn_evaluated", "mastery_update"]


async def test_incorrect_answer_triggers_remediation_with_citation(kg_graph, rag_index):
    repo = Repo(":memory:")
    llm = ScriptedOrchestratorLLM(["incorrect"])
    graph = build_orchestrator(llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph)
    config = {"configurable": {"thread_id": "sess-remediate"}}

    initial = _initial_state("sess-remediate")
    initial["current_kc"] = "PRC.005"
    result = await _run_turn(
        graph, config, "wrong answer", question="limited quantity thresholds", initial=initial
    )

    event_types = [e.event_type for e in repo.list_events("sess-remediate")]
    assert "mastery_update" in event_types
    assert "remediation" in event_types or "knowledge_gap" in event_types
    if result["citations"]:
        assert result["citations"][0]["doc_id"]


async def test_opt_out_emits_session_stop_and_skips_mastery(kg_graph, rag_index):
    repo = Repo(":memory:")
    llm = ScriptedOrchestratorLLM(["off_topic"])
    graph = build_orchestrator(llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph)
    config = {"configurable": {"thread_id": "sess-optout"}}

    result = await _run_turn(
        graph, config, "not now, please", initial=_initial_state("sess-optout")
    )

    events = repo.list_events("sess-optout")
    assert [e.event_type for e in events] == ["turn_evaluated", "session_stop"]
    assert result["mastery"] == {}
    assert result["turn_index"] == 0
    # The employee's own message is still recorded (it happened) even though the
    # turn ends before a reply is composed — only the assistant side is skipped.
    assert result["messages"] == [{"role": "user", "content": "not now, please"}]


# --- resume across turns -------------------------------------------------------


async def test_resume_across_twelve_turns_and_dropped_graph(tmp_path, kg_graph, rag_index):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    repo = Repo(":memory:")
    db_path = str(tmp_path / "checkpoints.sqlite")
    config = {"configurable": {"thread_id": "sess-resume-12"}}
    classifications = ["correct", "incorrect", "partial", "correct"] * 3 + ["correct"]
    llm = ScriptedOrchestratorLLM(classifications)

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        graph = build_orchestrator(
            llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph, checkpointer=saver
        )
        state = await _run_turn(
            graph, config, "an answer", initial=_initial_state("sess-resume-12")
        )
        for _ in range(11):
            state = await _run_turn(graph, config, "an answer")
        mastery_before_drop = dict(state["mastery"])
        messages_before_drop = list(state["messages"])

    assert state["turn_index"] == 12
    # One user + one assistant message per turn.
    assert len(messages_before_drop) == 24

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver2:
        graph2 = build_orchestrator(
            llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph, checkpointer=saver2
        )
        snapshot = await graph2.aget_state(config)
        assert snapshot.values["turn_index"] == 12
        assert snapshot.values["mastery"] == mastery_before_drop
        assert snapshot.values["messages"] == messages_before_drop

        resumed = await _run_turn(graph2, config, "one more answer")
        assert resumed["turn_index"] == 13


async def test_opt_out_then_resume_preserves_mastery_and_facts(tmp_path, kg_graph, rag_index):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    repo = Repo(":memory:")
    db_path = str(tmp_path / "checkpoints.sqlite")
    config = {"configurable": {"thread_id": "sess-pause-resume"}}

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        llm = ScriptedOrchestratorLLM(["correct", "off_topic"])
        graph = build_orchestrator(
            llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph, checkpointer=saver
        )

        state = await _run_turn(
            graph, config, "gloves", initial=_initial_state("sess-pause-resume")
        )
        mastery_at_pause = dict(state["mastery"])
        kc_at_pause = state["current_kc"]

        paused = await _run_turn(graph, config, "not now")
        assert paused["mastery"] == mastery_at_pause
        assert paused["current_kc"] == kc_at_pause

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver2:
        llm2 = ScriptedOrchestratorLLM(["correct"])
        graph2 = build_orchestrator(
            llm=llm2, index=rag_index, repo=repo, kg_graph=kg_graph, checkpointer=saver2
        )
        snapshot = await graph2.aget_state(config)
        assert snapshot.values["mastery"] == mastery_at_pause
        assert snapshot.values["current_kc"] == kc_at_pause

        resumed = await _run_turn(graph2, config, "gloves again")
        assert resumed["mastery"][kc_at_pause] > mastery_at_pause.get(kc_at_pause, 0.0)


# --- session close / SessionSummary -------------------------------------------


def test_close_session_emits_summary_with_deltas_and_risks():
    repo = Repo(":memory:")
    summary = close_session(
        repo,
        session_id="sess-close",
        employee_id="emp-1",
        mastery_before={"SAF.001": 0.3},
        mastery_after={"SAF.001": 0.6, "SAF.002": 0.2},
    )
    assert summary.mastery_deltas["SAF.001"] == pytest.approx(0.3)
    assert summary.not_for_use_in == ["performance_management", "termination"]
    low_mastery_risks = [r for r in summary.risks if r.kc_id == "SAF.002"]
    assert low_mastery_risks

    archived = repo.get_archived_session("sess-close")
    assert archived == summary


# --- compose_delivery is terminal -----------------------------------------------


class _RepeatingComposeLLM:
    """Always tries to call `compose_delivery` again, no matter what — simulates a
    model that never decides it's "done" on its own. Proves `route_after_tools` cuts
    the turn off after the first call rather than relying on the model to stop."""

    def __init__(self) -> None:
        self.compose_calls = 0

    async def extract(self, output_model, system, user):
        name = getattr(output_model, "__name__", "")
        if output_model is TurnEvaluation:
            return TurnEvaluation(
                kc_id="SAF.001",
                classification="correct",
                confidence=0.9,
                language="en",
                sentiment="neutral",
            )
        if name == "DeliveryMessage":
            self.compose_calls += 1
            return output_model(text=f"draft #{self.compose_calls}")
        raise AssertionError(f"unexpected output_model {output_model}")

    async def acall_with_tools(self, messages, tools):
        ai_tool_calls = [
            call["name"]
            for m in messages
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for call in m.tool_calls
        ]
        last_tool = ai_tool_calls[-1] if ai_tool_calls else None
        call_id = f"call-{len(ai_tool_calls)}"
        if last_tool is None:
            return AIMessage(
                content="", tool_calls=[{"name": "assess_reply", "args": {}, "id": call_id}]
            )
        # Always tries compose_delivery again, whether it's the first attempt or not.
        return AIMessage(
            content="", tool_calls=[{"name": "compose_delivery", "args": {}, "id": call_id}]
        )


async def test_compose_delivery_is_terminal_even_if_model_calls_it_again(kg_graph, rag_index):
    repo = Repo(":memory:")
    llm = _RepeatingComposeLLM()
    graph = build_orchestrator(llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph)
    config = {"configurable": {"thread_id": "sess-repeat-compose"}}

    result = await _run_turn(graph, config, "gloves", initial=_initial_state("sess-repeat-compose"))

    # Only the first compose_delivery call's text made it through, even though the
    # (misbehaving) model kept trying to call it again.
    assert llm.compose_calls == 1
    assert result["messages"][-1]["content"] == "draft #1"


# --- conversation history reaches compose_delivery ------------------------------


class _TranscriptCapturingLLM:
    """Grades every reply as correct and always composes directly, capturing every
    `compose_delivery` user prompt so a test can assert whether a prior turn's own
    reply shows up in a later turn's `<conversation_so_far>` block."""

    def __init__(self) -> None:
        self.delivery_prompts: list[str] = []

    async def extract(self, output_model, system, user):
        name = getattr(output_model, "__name__", "")
        if output_model is TurnEvaluation:
            return TurnEvaluation(
                kc_id="SAF.001",
                classification="correct",
                confidence=0.9,
                language="en",
                sentiment="neutral",
            )
        if name == "DeliveryMessage":
            self.delivery_prompts.append(user)
            return output_model(text=f"reply #{len(self.delivery_prompts)}")
        raise AssertionError(f"unexpected output_model {output_model}")

    async def acall_with_tools(self, messages, tools):
        ai_tool_calls = [
            call["name"]
            for m in messages
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for call in m.tool_calls
        ]
        if not ai_tool_calls:
            return AIMessage(
                content="", tool_calls=[{"name": "assess_reply", "args": {}, "id": "c0"}]
            )
        if ai_tool_calls[-1] == "assess_reply":
            return AIMessage(
                content="", tool_calls=[{"name": "compose_delivery", "args": {}, "id": "c1"}]
            )
        return AIMessage(content="done")


async def test_compose_delivery_sees_prior_turns_but_not_the_first(kg_graph, rag_index):
    repo = Repo(":memory:")
    llm = _TranscriptCapturingLLM()
    graph = build_orchestrator(
        llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph, checkpointer=MemorySaver()
    )
    config = {"configurable": {"thread_id": "sess-transcript"}}

    await _run_turn(graph, config, "first answer", initial=_initial_state("sess-transcript"))
    await _run_turn(graph, config, "second answer")

    assert len(llm.delivery_prompts) == 2
    # First turn: this turn's own employee message is visible (added before
    # compose_delivery runs), but there's no prior Sofía reply to echo back yet.
    assert "first answer" in llm.delivery_prompts[0]
    assert "reply #1" not in llm.delivery_prompts[0]
    # Second turn: sees both the employee's first answer and Sofía's own first reply.
    assert "first answer" in llm.delivery_prompts[1]
    assert "reply #1" in llm.delivery_prompts[1]


def test_session_progress_reports_latest_classification_per_kc(kg_graph):
    repo = Repo(":memory:")
    repo.append_event(
        "sess-progress",
        0,
        "turn_evaluated",
        {"kc_id": "SAF.001", "classification": "incorrect"},
    )
    repo.append_event(
        "sess-progress",
        1,
        "turn_evaluated",
        {"kc_id": "SAF.001", "classification": "correct"},
    )
    repo.append_event(
        "sess-progress",
        2,
        "turn_evaluated",
        {"kc_id": "BEH.001", "classification": "off_topic"},
    )

    progress = _session_progress(repo.list_events("sess-progress"), kg_graph)

    assert progress is not None
    assert "3 question(s) asked" in progress
    # Latest classification wins (correct, not the earlier incorrect attempt).
    assert "PPE selection and correct use per zone: correct" in progress
    # off_topic turns don't contribute a result.
    assert "BEH.001" not in progress
    assert "Shift handover" not in progress


class _ClosingCapturingLLM:
    """Grades once as correct, then composes with `closing=True`, capturing the
    delivery subagent's user prompt so a test can assert the wrap-up carries
    `<session_progress>` and skips the next question."""

    def __init__(self) -> None:
        self.delivery_prompts: list[str] = []

    async def extract(self, output_model, system, user):
        name = getattr(output_model, "__name__", "")
        if output_model is TurnEvaluation:
            return TurnEvaluation(
                kc_id="SAF.001",
                classification="correct",
                confidence=0.9,
                language="en",
                sentiment="neutral",
            )
        if name == "DeliveryMessage":
            self.delivery_prompts.append(user)
            return output_model(text="That's all for today!")
        raise AssertionError(f"unexpected output_model {output_model}")

    async def acall_with_tools(self, messages, tools):
        ai_tool_calls = [
            call["name"]
            for m in messages
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for call in m.tool_calls
        ]
        if not ai_tool_calls:
            return AIMessage(
                content="", tool_calls=[{"name": "assess_reply", "args": {}, "id": "c0"}]
            )
        if ai_tool_calls[-1] == "assess_reply":
            return AIMessage(
                content="",
                tool_calls=[{"name": "compose_delivery", "args": {"closing": True}, "id": "c1"}],
            )
        return AIMessage(content="done")


async def test_closing_wrap_up_skips_next_question_and_includes_results(kg_graph, rag_index):
    repo = Repo(":memory:")
    llm = _ClosingCapturingLLM()
    graph = build_orchestrator(llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph)
    config = {"configurable": {"thread_id": "sess-closing"}}

    result = await _run_turn(graph, config, "gloves", initial=_initial_state("sess-closing"))

    assert len(llm.delivery_prompts) == 1
    prompt = llm.delivery_prompts[0]
    assert "<session_progress>" in prompt
    assert "PPE selection and correct use per zone: correct" in prompt
    # Wrap-up shouldn't invite another question.
    assert "Next training question topic" not in prompt
    assert result["messages"][-1]["content"] == "That's all for today!"


# --- session-open turn ---------------------------------------------------------


class _SessionOpenLLM:
    """Always composes a welcome directly — the policy `ORCHESTRATOR_SYSTEM_PROMPT`
    asks for when `is_session_open` is set. Captures the `compose_delivery` user
    prompt so tests can assert `employee_profile` made it into context."""

    def __init__(self) -> None:
        self.delivery_prompts: list[str] = []

    async def extract(self, output_model, system, user):
        name = getattr(output_model, "__name__", "")
        if name == "DeliveryMessage":
            self.delivery_prompts.append(user)
            return output_model(text="Welcome! Let's get started.")
        raise AssertionError(f"unexpected output_model {output_model}")

    async def acall_with_tools(self, messages, tools):
        ai_tool_calls = [
            call["name"]
            for m in messages
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
            for call in m.tool_calls
        ]
        if not ai_tool_calls:
            return AIMessage(
                content="", tool_calls=[{"name": "compose_delivery", "args": {}, "id": "call-0"}]
            )
        return AIMessage(content="done")


class _MisbehavingSessionOpenLLM:
    """Calls `assess_reply` first despite `is_session_open` — tests the orchestrator's
    guard, not a real model's behavior."""

    async def extract(self, output_model, system, user):
        name = getattr(output_model, "__name__", "")
        if name == "DeliveryMessage":
            return output_model(text="Welcome!")
        raise AssertionError(f"unexpected output_model {output_model}")

    async def acall_with_tools(self, messages, tools):
        tool_results = [m.content for m in messages if isinstance(m, ToolMessage)]
        if not tool_results:
            return AIMessage(
                content="", tool_calls=[{"name": "assess_reply", "args": {}, "id": "call-0"}]
            )
        if len(tool_results) == 1:
            assert "session-open turn" in tool_results[-1]
            return AIMessage(
                content="", tool_calls=[{"name": "compose_delivery", "args": {}, "id": "call-1"}]
            )
        return AIMessage(content="done")


async def test_session_open_turn_composes_welcome_without_grading(kg_graph, rag_index):
    repo = Repo(":memory:")
    from app.schemas.extraction import PersonalFact

    repo.add_fact("emp-1", PersonalFact(fact_type="preferred_name", value="Sam", confidence=0.9))

    llm = _SessionOpenLLM()
    graph = build_orchestrator(llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph)
    config = {"configurable": {"thread_id": "sess-open"}}

    initial = {**_initial_state("sess-open"), "is_session_open": True}
    result = await _run_turn(graph, config, "", initial=initial)

    assert result["mastery"] == {}
    assert result["turn_index"] == 1
    assert result["messages"][-1]["content"] == "Welcome! Let's get started."
    assert repo.list_events("sess-open") == []
    assert any("Sam" in prompt for prompt in llm.delivery_prompts)


async def test_session_open_turn_rejects_assess_reply(kg_graph, rag_index):
    repo = Repo(":memory:")
    llm = _MisbehavingSessionOpenLLM()
    graph = build_orchestrator(llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph)
    config = {"configurable": {"thread_id": "sess-open-guard"}}

    initial = {**_initial_state("sess-open-guard"), "is_session_open": True}
    result = await _run_turn(graph, config, "", initial=initial)

    assert result["mastery"] == {}
    assert repo.list_events("sess-open-guard") == []


# --- replay (best-effort auditability, see CLAUDE.md caveat) ------------------


async def test_mastery_is_replayable_when_policy_is_followed(kg_graph, rag_index):
    """Not a guarantee of the architecture (CLAUDE.md documents that gap) --
    this proves the plumbing preserves replayability when the scripted policy
    follows the same grade-then-update sequence the system prompt asks for."""

    repo = Repo(":memory:")
    classifications = ["correct", "incorrect", "partial", "correct", "correct"]
    llm = ScriptedOrchestratorLLM(classifications)
    graph = build_orchestrator(
        llm=llm, index=rag_index, repo=repo, kg_graph=kg_graph, checkpointer=MemorySaver()
    )
    config = {"configurable": {"thread_id": "sess-replay"}}

    await _run_turn(graph, config, "an answer", initial=_initial_state("sess-replay"))
    for _ in range(len(classifications) - 1):
        await _run_turn(graph, config, "an answer")

    final_mastery = repo.get_mastery("emp-1")

    replayed: dict[str, float] = {}
    for event in repo.list_events("sess-replay"):
        if event.event_type != "turn_evaluated":
            continue
        kc_id = event.payload["kc_id"]
        classification = event.payload["classification"]
        if classification == "off_topic":
            continue
        prior = replayed.get(kc_id, bkt.DEFAULT_PARAMS.p_init)
        replayed[kc_id] = bkt.update(prior, classification)

    assert replayed == final_mastery
