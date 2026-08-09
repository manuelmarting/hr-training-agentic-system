"""Turn an approved draft into a runtime graph YAML — and back, for re-review.

`materialize` is a pure transform: draft → `KnowledgeComponent[]`, denormalizing the
edge list into each KC's `prerequisites`. It does *not* validate — the Approve endpoint
runs `validate_draft` first and refuses to call here on any blocking item (plan §5), so
materialization stays a straight mapping with a single responsibility.

`provenance` is carried straight through into `graph.yaml` (see `app.kg.loader`'s
docstring for why). `origin` is dropped — it's authoring-only bookkeeping with no
runtime use — so `draft_from_graph_yaml`, the inverse used to re-open a committed graph
in the studio, always comes back with `origin="manual"`, but real `provenance` intact.
"""

from __future__ import annotations

from pathlib import Path

from app.kg.loader import KnowledgeComponent, Provenance, dump_kcs, kcs_to_yaml, load_kcs
from app.studio.schemas import GraphDraft, ProposedEdge, ProposedKC


def materialize(draft: GraphDraft) -> list[KnowledgeComponent]:
    """Map an (assumed-valid) draft to runtime KCs with prerequisites denormalized."""
    prereqs = _prerequisites_by_target(draft)
    return [
        KnowledgeComponent(
            id=kc.id,
            name=kc.name,
            domain=kc.domain,
            description=kc.description,
            regulation=kc.regulation,
            known_misconceptions=list(kc.known_misconceptions),
            superseded_by_kc_id=kc.superseded_by_kc_id,
            provenance=_omit_if_empty(kc.provenance),
            prerequisites=prereqs.get(kc.id, []),
        )
        for kc in draft.kcs
    ]


def materialize_to_yaml(draft: GraphDraft) -> str:
    """The runtime YAML text for an approved draft (used by the demo preview endpoint)."""
    return kcs_to_yaml(materialize(draft), role=draft.role)


def write_graph(draft: GraphDraft, path: str | Path) -> list[KnowledgeComponent]:
    """Write the approved draft to a runtime graph file and return the materialized KCs."""
    kcs = materialize(draft)
    dump_kcs(kcs, path, role=draft.role)
    return kcs


def draft_from_graph_yaml(path: str | Path, *, draft_id: str) -> GraphDraft:
    """Re-open a committed runtime graph as an editable draft (inverse of `materialize`).

    Prerequisites are re-expanded into explicit edges. Each KC's `provenance` comes
    straight from the file; a KC with none (a graph written before the runtime format
    carried provenance, or hand-edited without going through Approve) comes back with
    empty provenance, correctly requiring a human to attach sources before re-approval.
    """
    kcs = load_kcs(path)
    proposed_kcs = [
        ProposedKC(
            id=kc.id,
            name=kc.name,
            domain=kc.domain,
            description=kc.description,
            regulation=kc.regulation,
            known_misconceptions=list(kc.known_misconceptions),
            superseded_by_kc_id=kc.superseded_by_kc_id,
            provenance=kc.provenance or Provenance(doc_id="", heading="", excerpt=""),
            origin="manual",
        )
        for kc in kcs
    ]
    edges = [
        ProposedEdge(
            source_kc_id=prereq,
            target_kc_id=kc.id,
            rationale="prerequisite from committed graph",
            origin="manual",
        )
        for kc in kcs
        for prereq in kc.prerequisites
    ]
    return GraphDraft(draft_id=draft_id, kcs=proposed_kcs, edges=edges)


def _omit_if_empty(provenance: Provenance) -> Provenance | None:
    """An all-empty provenance means "not yet attached" — write nothing rather than a
    block of empty strings, matching how `regulation`/`superseded_by_kc_id` are omitted.
    """
    if provenance.doc_id or provenance.heading or provenance.excerpt:
        return provenance
    return None


def _prerequisites_by_target(draft: GraphDraft) -> dict[str, list[str]]:
    """target_kc_id → sorted list of prerequisite source ids, from the edge list."""
    by_target: dict[str, list[str]] = {}
    for edge in draft.edges:
        by_target.setdefault(edge.target_kc_id, []).append(edge.source_kc_id)
    return {target: sorted(set(sources)) for target, sources in by_target.items()}
