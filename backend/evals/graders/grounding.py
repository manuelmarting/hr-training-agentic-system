"""LLM-judge faithfulness grading for remediation replies: does every factual claim
in a composed explanation follow from its cited SOP excerpt?"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.agent.llm import StructuredLLM

FaithfulnessLabel = Literal["entailed", "unsupported", "contradicted"]


class FaithfulnessVerdict(BaseModel):
    verdict: FaithfulnessLabel
    reasoning: str


_SYSTEM = (
    "You are grading whether a training assistant's explanation is faithful to its "
    "cited source excerpt. Read the excerpt and the explanation. Judge:\n"
    "- entailed: every factual claim in the explanation follows from the excerpt "
    "(paraphrasing and reasonable elaboration are fine; adding facts not in the "
    "excerpt is not)\n"
    "- unsupported: the explanation adds a claim the excerpt doesn't support\n"
    "- contradicted: the explanation states something the excerpt directly "
    "contradicts\n"
    "Be strict: only 'entailed' if nothing is added or reversed."
)


async def judge_faithfulness(
    llm: StructuredLLM, *, composed_text: str, excerpt: str, citation_heading: str
) -> FaithfulnessVerdict:
    user = (
        f"Source excerpt (from {citation_heading!r}):\n{excerpt}\n\n"
        f"Explanation to grade:\n{composed_text}"
    )
    return await llm.extract(FaithfulnessVerdict, _SYSTEM, user)
