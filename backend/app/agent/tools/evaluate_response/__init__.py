"""Turn evaluation: the one LLM call per turn (plan §3, §4 Phase 2).

Grades the employee's answer, tags language and sentiment. Prompt hardening: the
employee's raw text is always delivered inside a delimited `<employee_message>` block
with an explicit instruction that its content is data, never instruction — an
injection attempt is expected to come back classified `off_topic`, never as anything
that changes grading. `opt_out` is computed here in Python from a keyword check, not
by the LLM (CLAUDE.md: "Python computes").
"""

import logging

from app.agent.llm import StructuredLLM, StructuredLLMError
from app.prompt_loading import load_prompt
from app.schemas.extraction import TurnEvaluation

logger = logging.getLogger(__name__)

EVALUATE_SYSTEM_PROMPT = load_prompt(__file__, "system")

# Opt-out phrases in the three supported languages (PRD §7 user opt-out / session pause).
_OPT_OUT_KEYWORDS = [
    "not now",
    "don't want",
    "do not want",
    "stop asking",
    "later",
    "pause",
    "no quiero",
    "ahora no",
    "más tarde",
    "nu vreau",
    "nu acum",
    "mai târziu",
]


def _is_opt_out(employee_text: str) -> bool:
    text = employee_text.lower()
    return any(keyword in text for keyword in _OPT_OUT_KEYWORDS)


def _build_user_prompt(kc_id: str, question: str, employee_text: str) -> str:
    return (
        f"Knowledge component: {kc_id}\n"
        f"Question asked: {question}\n\n"
        "<employee_message>\n"
        f"{employee_text}\n"
        "</employee_message>"
    )


async def evaluate_turn(
    llm: StructuredLLM, *, kc_id: str, question: str, employee_text: str
) -> TurnEvaluation:
    """Classify one employee reply. Never raises — a repair failure falls back to a
    safe, low-confidence `off_topic` evaluation so the graph can route to a human
    rather than crash (CLAUDE.md: "never a crash")."""
    user_prompt = _build_user_prompt(kc_id, question, employee_text)
    try:
        evaluation = await llm.extract(TurnEvaluation, EVALUATE_SYSTEM_PROMPT, user_prompt)
    except StructuredLLMError as error:
        logger.warning("turn evaluation failed after repair, falling back: %s", error)
        evaluation = TurnEvaluation(
            kc_id=kc_id,
            classification="off_topic",
            confidence=0.0,
            language="en",
            sentiment="neutral",
        )

    # kc_id is context the caller already knows deterministically — never trust the
    # LLM to echo it back correctly (it's not a classification).
    updates: dict = {"kc_id": kc_id}
    if evaluation.classification == "off_topic" and _is_opt_out(employee_text):
        updates["opt_out"] = True
    return evaluation.model_copy(update=updates)
