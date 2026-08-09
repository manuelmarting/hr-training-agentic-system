"""Fail-closed personal-fact gate, stage 1 of 2 (PRD §7, CLAUDE.md).

A `PersonalFact` is stored only if BOTH classifiers pass: this module's pattern
classifier (stage 1, deterministic, no LLM) and an LLM classifier (stage 2, added in
Phase 2 alongside the rest of the LLM boundary). `gate()` is the fail-closed
combinator both stages feed into — an absent or negative stage-2 verdict is always a
reject, never an implicit pass, so wiring in the real LLM call later can't
accidentally loosen this.

`fact_type` is already restricted to the allowlist at the type level
(`PersonalFactType` in `schemas/extraction.py`), so the risk this module guards
against is a smuggled special-category *value* under an allowed type — e.g.
`fact_type="preferred_language"` with `value="I can't work Fridays, dialysis"`.
"""

from typing import Literal

from pydantic import BaseModel

from app.schemas.extraction import PersonalFact

# Special categories that must never be stored, regardless of fact_type (PRD §7):
# health, religion, ethnicity, union membership, sexuality, biometrics.
_DENYLIST: dict[str, list[str]] = {
    "health": [
        "diagnos",
        "diabetes",
        "cancer",
        "medication",
        "pregnan",
        "disab",
        "mental health",
        "therapy",
        "illness",
        "dialysis",
        "hiv",
    ],
    "religion": ["muslim", "christian", "jewish", "hindu", "buddhist", "religion", "religious"],
    "ethnicity": ["ethnicity", "race", "racial", "nationality is"],
    "union": ["union member", "trade union", "unioniz", "collective bargaining"],
    "sexuality": ["gay", "lesbian", "bisexual", "sexual orientation", "transgender"],
    "biometric": ["fingerprint", "facial recognition", "biometric", "retina scan"],
}


class GateResult(BaseModel):
    allowed: bool
    stage: Literal["pattern", "llm", "combined"]
    reason: str | None = None
    category: str | None = None


def pattern_check(fact: PersonalFact) -> GateResult:
    """Stage 1: keyword/pattern scan of the fact's value for special-category content."""
    value_lower = fact.value.lower()
    for category, keywords in _DENYLIST.items():
        for keyword in keywords:
            if keyword in value_lower:
                return GateResult(
                    allowed=False,
                    stage="pattern",
                    reason=f"value contains special-category keyword: {keyword!r}",
                    category=category,
                )
    return GateResult(allowed=True, stage="pattern")


def gate(fact: PersonalFact, llm_verdict: bool | None) -> GateResult:
    """Fail-closed combinator: store only if pattern passes AND llm_verdict is True.

    `llm_verdict=None` models an LLM-call failure — treated as a reject, matching
    PRD §7's fail-closed requirement (an error is not a pass).
    """
    pattern_result = pattern_check(fact)
    if not pattern_result.allowed:
        return pattern_result

    if llm_verdict is not True:
        reason = "LLM classifier error" if llm_verdict is None else "LLM classifier did not pass"
        return GateResult(allowed=False, stage="llm", reason=reason)

    return GateResult(allowed=True, stage="combined")
