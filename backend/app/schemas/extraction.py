"""Structured LLM-extraction models (PRD §6.1, §7).

Every LLM call in the agent core goes through `.with_structured_output()` against one
of these four models (CLAUDE.md: "Pydantic everywhere data crosses a boundary"). The
LLM only ever produces a classification/extraction; nothing here computes a mastery
number or a gating decision — that stays in `app/mastery/bkt.py` and `app/kg/`.
"""

from typing import Literal

from pydantic import BaseModel, Field

Classification = Literal["correct", "incorrect", "partial", "off_topic"]
Language = Literal["es", "en", "ro"]
Sentiment = Literal["neutral", "confident", "frustrated", "distressed"]

# Allowlisted personal-fact types (PRD §7: "allowlisted types only"). Anything not in
# this set — health, religion, ethnicity, union membership, sexuality, biometrics — is
# a special category and must never reach this model; `memory/pii_gate.py` enforces
# that before a `PersonalFact` is ever constructed from LLM output.
PersonalFactType = Literal[
    "preferred_name",
    "preferred_language",
    "shift_pattern",
    "contact_time_preference",
    "channel_preference",
]


class TurnEvaluation(BaseModel):
    """The one LLM call per turn: grade the answer, tag language and sentiment.

    Backs the orchestrator's single `assess_reply` tool (`app/agent/tools.py`), which
    grades, updates BKT mastery, and advances the KC selection all from this one
    evaluation — there is no longer a separate grade/update-mastery/select-next-kc
    split at the tool-calling layer.

    `opt_out` is not produced by the LLM — the graph's opt-out node sets it after
    inspecting `classification == "off_topic"` plus a keyword check on the raw
    employee text (plan §3 / Phase 2 item 4), so it defaults False here.
    """

    kc_id: str
    classification: Classification
    misconception_kc_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    language: Language
    sentiment: Sentiment
    opt_out: bool = False


class PersonalFact(BaseModel):
    """A non-PII fact extracted about the employee, pending the PII gate (PRD §7)."""

    fact_type: PersonalFactType
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class LearningRisk(BaseModel):
    """A flagged competency/engagement risk surfaced at session-summary time."""

    kc_id: str
    risk_type: Literal["low_mastery", "stalled_progress", "repeated_misconception", "knowledge_gap"]
    description: str
    severity: Literal["low", "medium", "high"]


class SessionSummary(BaseModel):
    """Emitted once per session close (PRD §7: "every session emits summary...").

    `not_for_use_in` is a fixed constraint tag, not something the LLM chooses — Sofía's
    output must never feed performance management (PRD §3 non-goals).
    """

    session_id: str
    mastery_deltas: dict[str, float] = Field(default_factory=dict)
    risks: list[LearningRisk] = Field(default_factory=list)
    not_for_use_in: list[str] = Field(
        default_factory=lambda: ["performance_management", "termination"]
    )
