"""Tool schemas for the orchestrator's ReAct loop.

Each `@tool` function's body is never called — `orchestrator.py`'s `tools_node`
dispatches on `tool_call["name"]` itself, so it can reach the deterministic
mastery/gating/citation logic and the per-turn state directly, instead of the model's
supplied arguments. That's a deliberate boundary, not an oversight: the LLM decides
*whether and when* to call a tool; Python still owns *what the tool actually does* and
*what data it acts on* (kc_id, mastery, employee_text) — the same "the LLM classifies,
Python computes" split as the rest of the codebase, now applied to orchestration
instead of computation. These functions exist only so `.bind_tools()` has a name,
description, and argument schema to advertise to the model.
"""

from langchain_core.tools import tool


@tool
def evaluate_response() -> str:
    """Grade the employee's most recent reply against the current knowledge
    component (correct, incorrect, partial, or off-topic, plus detected language,
    sentiment, and whether they seem to want to pause), persist the resulting
    mastery update using the fixed BKT formula, and advance to the next unlocked
    knowledge component if mastery clears threshold. One call does all three —
    there's no separate step to save the grade or pick what's next."""
    raise NotImplementedError("dispatched by orchestrator.py; never invoked directly")


@tool
def fetch_remediation(reason: str = "") -> str:
    """Look up a grounded SOP excerpt for the employee's apparent knowledge gap.
    `reason` is an optional short note on what they seem confused about, to help
    aim the search."""
    raise NotImplementedError("dispatched by orchestrator.py; never invoked directly")


@tool
def extract_facts() -> str:
    """Check the employee's reply for an allowlisted personal fact worth
    remembering (preferred name, language, shift pattern, contact-time preference).
    No-ops if nothing is found."""
    raise NotImplementedError("dispatched by orchestrator.py; never invoked directly")


@tool
def deliver_reply(closing: bool = False) -> str:
    """Compose and send this turn's actual reply to the employee, tailored to their
    detected sentiment/language. This is the only way anything reaches the employee.
    Set `closing=True` when this reply is today's wrap-up
    (per the session-length guidance) rather than the next question — the actual
    summary text is composed from session data, not from anything you write here."""
    raise NotImplementedError("dispatched by orchestrator.py; never invoked directly")


@tool
def end_session() -> str:
    """End the turn early — for example, because the employee wants to pause."""
    raise NotImplementedError("dispatched by orchestrator.py; never invoked directly")


ORCHESTRATOR_TOOLS = [
    evaluate_response,
    fetch_remediation,
    extract_facts,
    deliver_reply,
    end_session,
]
