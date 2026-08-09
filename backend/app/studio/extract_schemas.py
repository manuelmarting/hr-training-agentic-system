"""LLM-facing extraction schemas (plan §4).

These are what the model returns per structured-output call — narrower than the reviewed
`ProposedKC`/`ProposedEdge`. Ids are assigned by `reconcile.py`, not the model (a KC's
identity is a deterministic Python decision, never an LLM one); provenance `doc_id` is the
document being processed, so the model only supplies the `heading` + `excerpt`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.studio.schemas import Domain


class ExtractedKC(BaseModel):
    """A knowledge component proposed from a single document (pass A)."""

    name: str
    domain: Domain
    description: str
    regulation: str | None = None
    known_misconceptions: list[str] = Field(default_factory=list)
    heading: str  # nearest section heading — provenance
    excerpt: str  # verbatim span the KC was drawn from — provenance


class DocKCProposal(BaseModel):
    """Pass A output: the KCs one document requires a worker to hold."""

    kcs: list[ExtractedKC] = Field(default_factory=list)


class ExtractedEdge(BaseModel):
    """A prerequisite edge proposed at corpus level (pass B), referencing assigned ids."""

    source_kc_id: str
    target_kc_id: str
    rationale: str


class EdgeProposal(BaseModel):
    """Pass B output: which KCs must be mastered before which others."""

    edges: list[ExtractedEdge] = Field(default_factory=list)
