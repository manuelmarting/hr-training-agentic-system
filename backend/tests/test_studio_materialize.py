"""Materialization tests (plan §8): the seed graph IS an output of this pipeline.

The load-as-draft → materialize → reload round trip is what makes that claim checkable
rather than rhetorical (plan §2, phase 2).
"""

from pathlib import Path

import yaml

from app.kg.loader import Provenance, load_kcs
from app.studio.materialize import (
    draft_from_graph_yaml,
    materialize,
    materialize_to_yaml,
    write_graph,
)
from app.studio.schemas import GraphDraft, ProposedEdge, ProposedKC

SEED = Path(__file__).resolve().parents[1] / "app" / "kg" / "graph.yaml"


def _kc(kc_id: str, domain: str = "safety") -> ProposedKC:
    return ProposedKC(
        id=kc_id,
        name=f"KC {kc_id}",
        domain=domain,  # type: ignore[arg-type]
        description="desc",
        provenance=Provenance(doc_id="01", heading="h", excerpt="e"),
        origin="extracted",
    )


def _edge(source: str, target: str) -> ProposedEdge:
    return ProposedEdge(source_kc_id=source, target_kc_id=target, rationale="r", origin="extracted")


def test_seed_round_trips_structurally(tmp_path: Path) -> None:
    original = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    draft = draft_from_graph_yaml(SEED, draft_id="rt")
    out = tmp_path / "graph.yaml"
    write_graph(draft, out)
    roundtripped = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert roundtripped == original


def test_materialized_seed_loads_in_loader(tmp_path: Path) -> None:
    draft = draft_from_graph_yaml(SEED, draft_id="rt")
    out = tmp_path / "graph.yaml"
    write_graph(draft, out)
    assert load_kcs(out) == load_kcs(SEED)


def test_edges_become_prerequisites() -> None:
    draft = GraphDraft(
        draft_id="d",
        role="warehouse_operative",
        kcs=[_kc("SAF.002"), _kc("SAF.003"), _kc("SAF.004")],
        edges=[_edge("SAF.002", "SAF.003"), _edge("SAF.003", "SAF.004")],
    )
    kcs = {kc.id: kc for kc in materialize(draft)}
    assert kcs["SAF.003"].prerequisites == ["SAF.002"]
    assert kcs["SAF.004"].prerequisites == ["SAF.003"]
    assert kcs["SAF.002"].prerequisites == []


def test_multiple_prerequisites_sorted_and_deduped() -> None:
    draft = GraphDraft(
        draft_id="d",
        kcs=[_kc("SYS.001", "systems"), _kc("PRC.008", "process"), _kc("SYS.002", "systems")],
        edges=[
            _edge("SYS.001", "SYS.002"),
            _edge("PRC.008", "SYS.002"),
            _edge("SYS.001", "SYS.002"),  # duplicate edge
        ],
    )
    kcs = {kc.id: kc for kc in materialize(draft)}
    assert kcs["SYS.002"].prerequisites == ["PRC.008", "SYS.001"]


def test_origin_is_dropped_but_provenance_survives() -> None:
    draft = GraphDraft(draft_id="d", kcs=[_kc("SAF.001")], edges=[])
    yaml_text = materialize_to_yaml(draft)
    assert "origin" not in yaml_text
    assert "excerpt: e" in yaml_text


def test_empty_provenance_is_omitted_from_yaml() -> None:
    kc = _kc("SAF.001")
    kc.provenance = Provenance(doc_id="", heading="", excerpt="")
    draft = GraphDraft(draft_id="d", kcs=[kc], edges=[])
    yaml_text = materialize_to_yaml(draft)
    assert "provenance" not in yaml_text


def test_provenance_survives_write_and_reopen_round_trip(tmp_path: Path) -> None:
    kc = _kc("SAF.001")
    kc.provenance = Provenance(doc_id="04-fire-evac", heading="2. Alarms", excerpt="verbatim span")
    draft = GraphDraft(draft_id="d", kcs=[kc], edges=[])
    out = tmp_path / "graph.yaml"

    write_graph(draft, out)
    reopened = draft_from_graph_yaml(out, draft_id="rt")
    reopened_kc = next(k for k in reopened.kcs if k.id == "SAF.001")
    assert reopened_kc.provenance == kc.provenance
    assert reopened_kc.origin == "manual"  # origin is never persisted, always resets


def test_reopen_graph_without_provenance_synthesizes_empty(tmp_path: Path) -> None:
    draft = GraphDraft(draft_id="d", kcs=[_kc("SAF.001")], edges=[])
    draft.kcs[0].provenance = Provenance(doc_id="", heading="", excerpt="")
    out = tmp_path / "graph.yaml"
    write_graph(draft, out)

    reopened = draft_from_graph_yaml(out, draft_id="rt")
    reopened_kc = next(k for k in reopened.kcs if k.id == "SAF.001")
    assert reopened_kc.provenance == Provenance(doc_id="", heading="", excerpt="")
    assert reopened_kc.origin == "manual"


def test_regulation_and_misconceptions_survive() -> None:
    kc = _kc("PRC.005", "process")
    kc.regulation = "ADR"
    kc.known_misconceptions = ["limited vs excepted quantity"]
    draft = GraphDraft(draft_id="d", kcs=[kc], edges=[])
    out = materialize(draft)[0]
    assert out.regulation == "ADR"
    assert out.known_misconceptions == ["limited vs excepted quantity"]
