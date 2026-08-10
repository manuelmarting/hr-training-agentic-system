"""Grounded remediation: cite or abstain (PRD §7; plan §4 Phase 3).

The excerpt and its citation travel together as data — `citation`/`excerpt` are
structurally required together unless the reply abstains, a type-level invariant
enforced by `RemediationReply`'s validator, not a prompt instruction. Delivery
composition (`app/agent/tools/deliver_reply/__init__.py`) is what turns the excerpt into the
employee-facing explanation; it's allowed to paraphrase it (a deliberate tradeoff for
a more natural tone — see that module's docstring for the safety net that replaces the
"can't misquote, it never generates that part" guarantee this module used to provide
by splicing the excerpt in verbatim itself).

`fetch_remediation` is the pure primitive (query in, cited-or-abstained reply out).
`fetch_remediation_from_grade` is the tool-facing entry point the orchestrator's
`fetch_remediation` tool calls: it only builds the retrieval query from what the
orchestrator already knows (the KC, the question, and its own short note on the
misconception) — the orchestrator decides *whether* to call it (only for
'incorrect'/'partial' grades, never 'correct'/'off_topic'), grounding itself stays
exactly as strict either way.
"""

from pydantic import BaseModel, model_validator

from app.rag.retrieve import Abstain, Citation, Index, retrieve


class RemediationReply(BaseModel):
    excerpt: str | None = None
    citation: Citation | None = None
    abstained: bool = False
    knowledge_gap_reason: str | None = None

    @model_validator(mode="after")
    def _citation_and_excerpt_required_unless_abstained(self) -> "RemediationReply":
        if not self.abstained and (self.citation is None or self.excerpt is None):
            raise ValueError(
                "a non-abstaining remediation reply must carry both citation and excerpt"
            )
        if self.abstained and (self.citation is not None or self.excerpt is not None):
            raise ValueError("an abstained remediation reply must not carry citation/excerpt")
        return self


def fetch_remediation(
    index: Index, *, query: str, threshold: float | None = None
) -> RemediationReply:
    """Look up grounding for `query` (typically the KC/misconception being remediated)
    and produce either a cited excerpt or an abstain reply. Never raises for a
    retrieval miss — that's the abstain path, not an error."""
    kwargs = {} if threshold is None else {"threshold": threshold}
    outcome = retrieve(index, query, **kwargs)

    if isinstance(outcome, Abstain):
        return RemediationReply(abstained=True, knowledge_gap_reason=outcome.reason)

    return RemediationReply(excerpt=outcome.excerpt, citation=outcome.citation)


async def fetch_remediation_from_grade(
    index: Index, *, kc_id: str, question: str, reason: str
) -> RemediationReply:
    """Build a retrieval query from what the orchestrator already knows and look it
    up. Never raises — a retrieval miss is the abstain path, not an error."""
    query = f"{kc_id} {question} {reason}".strip()
    return fetch_remediation(index, query=query)
