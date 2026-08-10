"""Personal-fact extraction feeding the two-stage PII gate (plan §3, §4 Phase 2).

Stage 1 (`pii_gate.pattern_check`) runs first and is a short-circuit: if the value
already trips the pattern denylist there is no reason to spend an LLM call on it.
Stage 2 is this module's LLM special-category check. `pii_gate.gate()` is the
fail-closed combinator — an LLM error on stage 2 is passed through as `None`, which
`gate()` treats as a reject, never an implicit pass.

Employee text is delimited the same way as `nodes/evaluate.py` — data, never
instruction.
"""

import logging

from pydantic import BaseModel

from app.agent.llm import StructuredLLM, StructuredLLMError
from app.agent.tools.extract_facts.pii_gate import GateResult, gate, pattern_check
from app.prompt_loading import load_prompt
from app.schemas.extraction import PersonalFact

logger = logging.getLogger(__name__)

MEMORY_SYSTEM_PROMPT = load_prompt(__file__, "system")

SPECIAL_CATEGORY_SYSTEM_PROMPT = load_prompt(__file__, "special_category")


class _FactExtraction(BaseModel):
    """Internal structured-output envelope: an extraction turn may find nothing."""

    fact: PersonalFact | None = None


class _SpecialCategoryCheck(BaseModel):
    safe: bool


def _build_extraction_prompt(employee_text: str) -> str:
    return f"<employee_message>\n{employee_text}\n</employee_message>"


async def extract_fact(llm: StructuredLLM, *, employee_text: str) -> PersonalFact | None:
    """Stage-0 extraction: what fact (if any) does this message contain?

    Never raises — an extraction failure just means no fact is proposed this turn.
    """
    try:
        extraction = await llm.extract(
            _FactExtraction, MEMORY_SYSTEM_PROMPT, _build_extraction_prompt(employee_text)
        )
    except StructuredLLMError as error:
        logger.warning("fact extraction failed, skipping: %s", error)
        return None
    return extraction.fact


async def gate_fact(llm: StructuredLLM, fact: PersonalFact) -> GateResult:
    """Run both PII-gate stages for an already-extracted fact.

    Stage 1 short-circuits: a pattern-denylist hit skips the LLM call entirely.
    Stage 2's LLM error is treated as `None` (fail closed) rather than propagated.
    """
    pattern_result = pattern_check(fact)
    if not pattern_result.allowed:
        return pattern_result

    llm_verdict: bool | None
    try:
        check = await llm.extract(
            _SpecialCategoryCheck,
            SPECIAL_CATEGORY_SYSTEM_PROMPT,
            f"Proposed fact: {fact.fact_type} = {fact.value!r}",
        )
        llm_verdict = check.safe
    except StructuredLLMError as error:
        logger.warning("special-category check failed, failing closed: %s", error)
        llm_verdict = None

    return gate(fact, llm_verdict)


async def extract_and_gate_fact(
    llm: StructuredLLM, *, employee_text: str
) -> tuple[PersonalFact | None, GateResult | None]:
    """Convenience wrapper: extract, then gate if something was extracted.

    The caller (the future graph memory node, plan §4 Phase 4) is responsible for
    persisting the fact when `GateResult.allowed` and for logging every attempt —
    accepted or rejected — to the memory-extraction log (PRD §7).
    """
    fact = await extract_fact(llm, employee_text=employee_text)
    if fact is None:
        return None, None
    return fact, await gate_fact(llm, fact)
