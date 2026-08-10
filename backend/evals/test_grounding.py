"""Faithfulness evals for remediation: run the real retrieval + real paraphrasing
LLM call, then judge whether the composed explanation is entailed by its cited SOP
excerpt. Also covers the abstain path, where the correct behavior is refusal rather
than a fabricated citation. Run with: pytest evals -m eval -k grounding
"""

from __future__ import annotations

import pytest

from app.agent.tools.deliver_reply import ABSTAIN_TEXT, deliver_reply
from app.agent.tools.fetch_remediation import fetch_remediation_from_grade
from app.rag.retrieve import build_index_from_sops
from evals.graders.grounding import judge_faithfulness
from evals.harness import SOPS_DIR, build_agent_llm, build_judge_llm, load_cases

pytestmark = pytest.mark.eval

GROUNDED_CASES = load_cases("remediation_grounding.yaml")["grounded_cases"]
ABSTAIN_CASES = load_cases("remediation_grounding.yaml")["abstain_cases"]


@pytest.fixture
def llm():
    """The LLM that composes the remediation reply — i.e. the thing being graded."""
    return build_agent_llm()


@pytest.fixture
def judge_llm():
    """A separate LLM instance for faithfulness grading, so the composing model
    never grades its own output."""
    return build_judge_llm()


@pytest.fixture
def index():
    return build_index_from_sops(SOPS_DIR)


@pytest.mark.parametrize("case", GROUNDED_CASES, ids=[c["id"] for c in GROUNDED_CASES])
async def test_remediation_is_grounded(case, llm, judge_llm, index):
    reply = await fetch_remediation_from_grade(
        index, kc_id=case["kc_id"], question=case["question"], reason=case["reason"]
    )
    assert not reply.abstained, f"expected a grounded excerpt for {case['id']!r}, got an abstain"

    delivery = await deliver_reply(
        llm,
        language="en",
        sentiment="neutral",
        fallback_text=f"{reply.excerpt}\n\n— {reply.citation.doc_id}, {reply.citation.heading!r}",
        excerpt=reply.excerpt,
        citation=reply.citation,
    )

    verdict = await judge_faithfulness(
        judge_llm,
        composed_text=delivery.text,
        excerpt=reply.excerpt,
        citation_heading=reply.citation.heading,
    )
    assert verdict.verdict == "entailed", (
        f"{case['id']}: composed reply not entailed by excerpt — {verdict.reasoning}\n"
        f"excerpt: {reply.excerpt!r}\nreply: {delivery.text!r}"
    )
    assert delivery.citation == reply.citation, "citation must mirror state, not LLM output"


@pytest.mark.parametrize("case", ABSTAIN_CASES, ids=[c["id"] for c in ABSTAIN_CASES])
async def test_remediation_abstains_without_fabricating(case, llm, index):
    reply = await fetch_remediation_from_grade(
        index, kc_id=case["kc_id"], question=case["question"], reason=case["reason"]
    )
    assert reply.abstained, f"expected an abstain for {case['id']!r}, got a grounded reply"
    assert reply.citation is None
    assert reply.excerpt is None

    delivery = await deliver_reply(
        llm,
        language="en",
        sentiment="neutral",
        fallback_text=ABSTAIN_TEXT,
        abstain_reason=reply.knowledge_gap_reason,
    )
    assert delivery.citation is None, "an abstained reply must never carry a citation"
