"""Pydantic models for the KG-authoring studio (plan §3).

The runtime graph is only ever produced from a `GraphDraft` that passed
`validate.py` and an explicit Approve. These models are the wire + storage shape;
they are deliberately lenient about *content* (e.g. an empty provenance excerpt is
constructible) so that an in-progress draft always round-trips through storage and
its problems surface as reviewable blocking items rather than as construction
exceptions. `validate.py` owns the invariants that gate approval.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.kg.loader import Provenance

# Closed sets ---------------------------------------------------------------

Domain = Literal["safety", "equipment", "process", "systems", "behavioural"]
"""The five KC domains (VISION.md §6.2 / sops/README.md). Matches workflow 1's graph."""

Origin = Literal["extracted", "edited", "manual"]
"""Provenance of a node/edge in the review flow. `edited`/`manual` mark human touch —
the visible evidence that the human-in-the-loop step is real (plan §3)."""


class DraftStatus(str, Enum):
    """Lifecycle of a draft. A draft materializes to YAML only from `approved`."""

    EXTRACTING = "extracting"
    DRAFT = "draft"
    APPROVED = "approved"
    FAILED = "failed"


# Core models ---------------------------------------------------------------

# `Provenance` itself lives in app.kg.loader: the runtime graph carries it too (see that
# module's docstring), so it has one canonical shape shared by drafts and committed KCs.
# Fields may be empty on an in-progress draft; `validate.py` rejects empties at approval
# time. The reviewer is always shown the claim against this excerpt.


class ProposedKC(BaseModel):
    """A candidate knowledge component awaiting review."""

    id: str  # DOMAIN.NNN, assigned by reconcile.py
    name: str
    domain: Domain
    description: str
    regulation: str | None = None
    known_misconceptions: list[str] = Field(default_factory=list)
    superseded_by_kc_id: str | None = None
    provenance: Provenance  # required — no bare assertions
    origin: Origin


class ProposedEdge(BaseModel):
    """A candidate `prerequisite_of` edge: `source` must be mastered before `target`."""

    source_kc_id: str
    target_kc_id: str
    rationale: str
    provenance: Provenance | None = None  # None only for manually added edges
    origin: Origin


class GraphDraft(BaseModel):
    """A whole candidate graph for one role, edited wholesale by a single reviewer."""

    draft_id: str
    role: str = "warehouse_operative"
    status: DraftStatus = DraftStatus.DRAFT
    source_docs: list[str] = Field(default_factory=list)
    kcs: list[ProposedKC] = Field(default_factory=list)
    edges: list[ProposedEdge] = Field(default_factory=list)
