"""LLM-as-judge for conversation quality: does a turn's rendered reply read the way
an employee would expect (short, professional, friendly, engaging), and does it
correctly reflect what actually happened this turn (the grading classification, and
whether remediation ran)?"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.llm import StructuredLLM

Score = Literal[1, 2, 3, 4, 5]

PASS_THRESHOLD = 4


class ConversationQualityVerdict(BaseModel):
    tone_score: Score = Field(
        description="1=robotic/curt/off-putting, 5=short, professional, friendly, engaging"
    )
    educational_accuracy_score: Score = Field(
        description="1=misrepresents the grading outcome (e.g. praises a wrong answer), "
        "5=correctly reflects it"
    )
    appropriateness_score: Score = Field(
        description="1=next step doesn't match what happened this turn (invents content, "
        "ignores remediation), 5=matches"
    )
    reasoning: str


_SYSTEM = (
    "You are grading a frontline-employee training assistant's reply for a single "
    "chat turn. Score three dimensions 1-5 each:\n"
    "1. tone: short, professional, friendly, and engaging — the way an employee "
    "would expect a helpful coworker to write over chat, not a formal memo\n"
    "2. educational_accuracy: does the reply correctly reflect the grading outcome "
    "for this turn (e.g. it must not praise an answer that was actually graded "
    "incorrect, or correct an answer that was actually graded correct)\n"
    "3. appropriateness: does the reply's next step match what actually happened "
    "this turn (a grounded correction only if remediation ran; otherwise a plain "
    "next question)\n"
    "Be strict — a reply that is merely inoffensive is not automatically a 5."
)


async def judge_conversation_quality(
    llm: StructuredLLM,
    *,
    rendered_reply: str,
    classification: str,
    remediation_happened: bool,
) -> ConversationQualityVerdict:
    user = (
        f"This turn's actual grading classification: {classification}\n"
        f"Did remediation run this turn: {remediation_happened}\n\n"
        f"Reply to grade:\n{rendered_reply}"
    )
    return await llm.extract(ConversationQualityVerdict, _SYSTEM, user)
