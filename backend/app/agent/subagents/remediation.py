"""Remediation subagent: the orchestrator's `remediate` tool.

The orchestrator already decided a grounded excerpt is worth looking up (that's the
agentic part — it only calls this tool for 'incorrect'/'partial' grades, never
'correct'/'off_topic'). This module's job is narrower: turn that decision into a
retrieval query and a reply. Grounding itself stays exactly as strict as before —
`RemediationReply`'s validator still rejects a non-abstaining reply without a
citation, a type-level invariant, not a prompt instruction.
"""

from app.agent.nodes.remediate import RemediationReply
from app.agent.nodes.remediate import remediate as remediate_lookup
from app.rag.retrieve import Index


async def run_remediation(
    index: Index, *, kc_id: str, question: str, reason: str
) -> RemediationReply:
    """Build a retrieval query from what the orchestrator already knows (the KC,
    the question asked, and its own short note on the employee's misconception) and
    look it up. Never raises — a retrieval miss is the abstain path, not an error."""
    query = f"{kc_id} {question} {reason}".strip()
    return remediate_lookup(index, query=query)
