"""Draft validation (plan §4, §6).

Failures are returned as structured *blocking items* the review UI renders — never
raised as exceptions. The Approve endpoint re-runs this server-side and rejects on any
blocking item, so a plausible-looking KC can never reach a live graph without a human
having seen its source (plan §1's invariant).

Every check here is pure and deterministic: no LLM, no I/O.
"""

from typing import Literal

import networkx as nx
from pydantic import BaseModel

from app.studio.schemas import GraphDraft

IssueCode = Literal[
    "duplicate_kc_id",
    "missing_provenance",
    "dangling_edge",
    "self_loop",
    "cycle",
]


class ValidationIssue(BaseModel):
    """One blocking problem, addressable so the UI can click-to-focus it."""

    code: IssueCode
    message: str
    kc_id: str | None = None
    edge: tuple[str, str] | None = None  # (source_kc_id, target_kc_id)


class ValidationResult(BaseModel):
    ok: bool
    issues: list[ValidationIssue]


def validate_draft(draft: GraphDraft) -> ValidationResult:
    """Run every blocking check over a draft and collect the failures.

    Order: structural KC problems first (duplicate ids, missing provenance), then
    edge problems (dangling endpoints, self-loops), then the graph-level cycle check —
    which only considers edges whose endpoints are both real KCs, so a dangling edge
    can't masquerade as (or hide) a cycle.
    """
    issues: list[ValidationIssue] = []

    issues.extend(_duplicate_kc_ids(draft))
    issues.extend(_missing_provenance(draft))

    kc_ids = {kc.id for kc in draft.kcs}
    issues.extend(_edge_endpoints(draft, kc_ids))
    issues.extend(_cycles(draft, kc_ids))

    return ValidationResult(ok=not issues, issues=issues)


def _duplicate_kc_ids(draft: GraphDraft) -> list[ValidationIssue]:
    seen: set[str] = set()
    dupes: list[ValidationIssue] = []
    for kc in draft.kcs:
        if kc.id in seen:
            dupes.append(
                ValidationIssue(
                    code="duplicate_kc_id",
                    message=f"KC id '{kc.id}' is used by more than one node.",
                    kc_id=kc.id,
                )
            )
        seen.add(kc.id)
    return dupes


def _missing_provenance(draft: GraphDraft) -> list[ValidationIssue]:
    """A KC is unreviewable without a doc id and a verbatim excerpt (plan §1)."""
    issues: list[ValidationIssue] = []
    for kc in draft.kcs:
        p = kc.provenance
        if not p.doc_id.strip() or not p.excerpt.strip():
            issues.append(
                ValidationIssue(
                    code="missing_provenance",
                    message=(
                        f"KC '{kc.id}' has no source provenance "
                        "(a document id and a verbatim excerpt are required)."
                    ),
                    kc_id=kc.id,
                )
            )
    return issues


def _edge_endpoints(draft: GraphDraft, kc_ids: set[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for edge in draft.edges:
        pair = (edge.source_kc_id, edge.target_kc_id)
        if edge.source_kc_id == edge.target_kc_id:
            issues.append(
                ValidationIssue(
                    code="self_loop",
                    message=(
                        f"Edge '{edge.source_kc_id}' → itself: "
                        "a KC cannot be its own prerequisite."
                    ),
                    edge=pair,
                )
            )
            continue
        missing = [e for e in pair if e not in kc_ids]
        if missing:
            issues.append(
                ValidationIssue(
                    code="dangling_edge",
                    message=(
                        f"Edge {edge.source_kc_id} → {edge.target_kc_id} references "
                        f"unknown KC id(s): {', '.join(missing)}."
                    ),
                    edge=pair,
                )
            )
    return issues


def _cycles(draft: GraphDraft, kc_ids: set[str]) -> list[ValidationIssue]:
    """Prerequisite edges must form a DAG (plan §4). Report each cycle found."""
    graph = nx.DiGraph()
    graph.add_nodes_from(kc_ids)
    for edge in draft.edges:
        if (
            edge.source_kc_id in kc_ids
            and edge.target_kc_id in kc_ids
            and edge.source_kc_id != edge.target_kc_id
        ):
            graph.add_edge(edge.source_kc_id, edge.target_kc_id)

    if nx.is_directed_acyclic_graph(graph):
        return []

    issues: list[ValidationIssue] = []
    for cycle in nx.simple_cycles(graph):
        chain = " → ".join([*cycle, cycle[0]])
        issues.append(
            ValidationIssue(
                code="cycle",
                message=f"Prerequisite cycle: {chain}.",
                edge=(cycle[0], cycle[1] if len(cycle) > 1 else cycle[0]),
            )
        )
    return issues
