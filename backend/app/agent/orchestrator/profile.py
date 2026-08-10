"""Format stored facts into a short profile line for prompt context.

Pure and deterministic — no LLM call, and no PII gate call either: it only ever
formats facts that already passed `app/agent/tools/extract_facts/pii_gate.py` at write time
(`repo.add_fact`), so re-reading them into context never bypasses the allowlist.
"""

from app.persistence.repo import StoredFact
from app.schemas.extraction import PersonalFactType

_LABELS: dict[PersonalFactType, str] = {
    "preferred_name": "prefers to be called {value}",
    "preferred_language": "prefers {value}",
    "shift_pattern": "usual shift is {value}",
    "contact_time_preference": "best contact time is {value}",
}


def summarize_facts(facts: list[StoredFact]) -> str | None:
    """One short natural-language line from the latest fact of each type.

    `facts` is expected in id-ascending order (`Repo.list_facts`'s order), so a
    later entry for the same `fact_type` overwrites an earlier one, keeping only the
    most recent value per type. Returns `None` if there's nothing on record.
    """
    latest_by_type: dict[PersonalFactType, StoredFact] = {}
    for stored in facts:
        latest_by_type[stored.fact.fact_type] = stored

    if not latest_by_type:
        return None

    clauses = [
        _LABELS[fact_type].format(value=stored.fact.value)
        for fact_type, stored in latest_by_type.items()
    ]
    return "; ".join(clauses) + "."
