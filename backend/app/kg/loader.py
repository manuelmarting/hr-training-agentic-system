"""The runtime knowledge-graph format: read, write, and build the DiGraph.

This module is the single authority on the on-disk YAML shape. The runtime agent loads
its 24-KC graph through `load_kcs`; the studio's `materialize.py` writes an approved
draft through `dump_kcs`. Because both sides go through `KnowledgeComponent` here, a
materialized graph is *by construction* the shape the runtime reads.

The runtime format carries `provenance` (a pointer back to the source SOP excerpt a KC
was extracted from) but not `origin` — origin ("extracted"/"edited"/"manual") is purely
an in-review bookkeeping concept with no use once a KC is committed, whereas provenance
is worth keeping: it's the same grounding a KC's citation traces back to at runtime
(PRD §5), and keeping it on the KC means re-opening a committed graph in the studio for
review doesn't lose it. Prerequisite edges are stored denormalized as each KC's
`prerequisites` list (the ids that must be mastered first), which is exactly what
unlock traversal consumes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import networkx as nx
import yaml
from pydantic import BaseModel, Field

DEFAULT_MASTERY_THRESHOLD = 0.7

Domain = Literal["safety", "equipment", "process", "systems", "behavioural"]

# Field order in the serialized YAML. Optional fields are omitted when unset so the
# committed graph stays readable; `prerequisites` is always written (possibly `[]`).
_FIELD_ORDER = (
    "id",
    "name",
    "domain",
    "description",
    "regulation",
    "known_misconceptions",
    "superseded_by_kc_id",
    "provenance",
    "prerequisites",
)


class Provenance(BaseModel):
    """A pointer back to the source span a KC was extracted from."""

    doc_id: str  # e.g. "06-picking-packing-dg-coldchain"
    heading: str  # nearest section heading
    excerpt: str  # verbatim span the KC was extracted from


class KnowledgeComponent(BaseModel):
    """One node of the runtime graph."""

    id: str
    name: str
    domain: Domain
    description: str
    regulation: str | None = None
    known_misconceptions: list[str] = Field(default_factory=list)
    superseded_by_kc_id: str | None = None
    provenance: Provenance | None = None
    prerequisites: list[str] = Field(default_factory=list)


class GraphLoadError(ValueError):
    """The YAML parsed but does not describe a valid knowledge graph."""


def load_kcs(path: str | Path) -> list[KnowledgeComponent]:
    """Parse a graph YAML file into validated KCs, checking referential integrity.

    Raises `GraphLoadError` on duplicate ids, prerequisites pointing at unknown KCs, or
    a prerequisite cycle — the same invariants the studio's validator enforces, so an
    approved-and-materialized graph always reloads cleanly.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    kcs = [KnowledgeComponent.model_validate(item) for item in raw.get("knowledge_components", [])]
    _check_integrity(kcs)
    return kcs


def dump_kcs(kcs: list[KnowledgeComponent], path: str | Path, *, role: str) -> None:
    """Serialize KCs to a graph YAML file (the shape `load_kcs` reads back)."""
    Path(path).write_text(kcs_to_yaml(kcs, role=role), encoding="utf-8")


def kcs_to_yaml(kcs: list[KnowledgeComponent], *, role: str) -> str:
    """Deterministic YAML text for a set of KCs: KCs sorted by id, edges sorted."""
    ordered = sorted(kcs, key=lambda kc: kc.id)
    doc = {
        "role": role,
        "knowledge_components": [_kc_to_ordered_dict(kc) for kc in ordered],
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def build_digraph(kcs: list[KnowledgeComponent]) -> nx.DiGraph:
    """Build the prerequisite DiGraph: an edge prereq → kc for each `prerequisites` entry."""
    graph = nx.DiGraph()
    for kc in kcs:
        graph.add_node(kc.id, kc=kc)
    for kc in kcs:
        for prereq in kc.prerequisites:
            graph.add_edge(prereq, kc.id)
    return graph


class GateStatus(BaseModel):
    """Why a KC is or isn't assessable right now (PRD §7: unlock gating explained to the UI)."""

    kc_id: str
    gated: bool
    missing_prerequisites: list[str] = Field(default_factory=list)
    campaign_override: bool = False


def unlocked_kcs(
    graph: nx.DiGraph,
    mastery: dict[str, float],
    threshold: float = DEFAULT_MASTERY_THRESHOLD,
    campaign_scope: set[str] | None = None,
) -> set[str]:
    """KCs assessable right now: no prerequisites, all prerequisites mastered, or
    explicitly in `campaign_scope` (PRD §7: "unless explicitly in campaign scope,
    and logged" — the caller is responsible for logging the override, this only
    decides which KCs qualify for one).
    """
    campaign_scope = campaign_scope or set()
    return {
        kc_id
        for kc_id in graph.nodes
        if not is_gated(graph, kc_id, mastery, threshold, campaign_scope).gated
    }


def next_assessable_kc(
    graph: nx.DiGraph,
    mastery: dict[str, float],
    threshold: float = DEFAULT_MASTERY_THRESHOLD,
    campaign_scope: set[str] | None = None,
) -> str | None:
    """The lowest-id unlocked KC not yet mastered, or `None` if every unlocked KC is
    already at or above threshold (everything assessable right now has been mastered).
    """
    unlocked = unlocked_kcs(graph, mastery, threshold, campaign_scope)
    candidates = sorted(kc_id for kc_id in unlocked if mastery.get(kc_id, 0.0) < threshold)
    return candidates[0] if candidates else None


def is_gated(
    graph: nx.DiGraph,
    kc_id: str,
    mastery: dict[str, float],
    threshold: float = DEFAULT_MASTERY_THRESHOLD,
    campaign_scope: set[str] | None = None,
) -> GateStatus:
    """Explain whether `kc_id` is locked and, if so, by which unmastered prerequisites."""
    campaign_scope = campaign_scope or set()
    prerequisites = list(graph.predecessors(kc_id))
    missing = [p for p in prerequisites if mastery.get(p, 0.0) < threshold]

    if not missing:
        return GateStatus(kc_id=kc_id, gated=False)
    if kc_id in campaign_scope:
        return GateStatus(kc_id=kc_id, gated=False, campaign_override=True)
    return GateStatus(kc_id=kc_id, gated=True, missing_prerequisites=missing)


def invalidate_superseded(
    kcs: list[KnowledgeComponent], mastery: dict[str, float]
) -> dict[str, float]:
    """Drop mastery for KCs superseded by a newer KC, and re-queue the successor.

    A KC with `superseded_by_kc_id` set means the SOP behind it changed; the old
    mastery entry no longer reflects a valid assessment, and the successor KC (if it
    already had a mastery entry, e.g. carried over from a prior graph version) must be
    re-queued for fresh assessment rather than trusted (PRD §5 `superseded_by_kc_id`,
    §7 "invalidate and re-queue").
    """
    superseded_ids = {kc.id for kc in kcs if kc.superseded_by_kc_id is not None}
    successor_ids = {kc.superseded_by_kc_id for kc in kcs if kc.superseded_by_kc_id is not None}
    return {
        kc_id: value
        for kc_id, value in mastery.items()
        if kc_id not in superseded_ids and kc_id not in successor_ids
    }


def _kc_to_ordered_dict(kc: KnowledgeComponent) -> dict:
    data = kc.model_dump()
    out: dict = {}
    for key in _FIELD_ORDER:
        value = data[key]
        # Omit unset optionals to keep the committed graph clean; always keep prerequisites.
        if key in ("regulation", "superseded_by_kc_id", "provenance") and value is None:
            continue
        if key == "known_misconceptions" and not value:
            continue
        if key == "prerequisites":
            value = sorted(value)
        out[key] = value
    return out


def _check_integrity(kcs: list[KnowledgeComponent]) -> None:
    ids = [kc.id for kc in kcs]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise GraphLoadError(f"duplicate KC ids: {', '.join(sorted(dupes))}")

    id_set = set(ids)
    for kc in kcs:
        unknown = [p for p in kc.prerequisites if p not in id_set]
        if unknown:
            raise GraphLoadError(
                f"KC '{kc.id}' lists unknown prerequisite(s): {', '.join(unknown)}"
            )

    graph = build_digraph(kcs)
    if not nx.is_directed_acyclic_graph(graph):
        cycle = next(iter(nx.simple_cycles(graph)), [])
        raise GraphLoadError(f"prerequisite cycle: {' → '.join(cycle)}")
