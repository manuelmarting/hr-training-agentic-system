"""Unit tests for studio draft validation (plan §8: cycle / dangling / provenance)."""

from app.studio.schemas import (
    Domain,
    GraphDraft,
    ProposedEdge,
    ProposedKC,
    Provenance,
)
from app.studio.validate import validate_draft


def _kc(
    kc_id: str,
    domain: Domain = "safety",
    *,
    doc_id: str = "01-ppe-manual-handling",
    excerpt: str = "Operatives must wear the PPE specified for the zone.",
    origin: str = "extracted",
) -> ProposedKC:
    return ProposedKC(
        id=kc_id,
        name=f"KC {kc_id}",
        domain=domain,
        description="desc",
        provenance=Provenance(doc_id=doc_id, heading="1. PPE", excerpt=excerpt),
        origin=origin,  # type: ignore[arg-type]
    )


def _edge(source: str, target: str) -> ProposedEdge:
    return ProposedEdge(
        source_kc_id=source,
        target_kc_id=target,
        rationale="source is required before target",
        origin="extracted",
    )


def _draft(kcs: list[ProposedKC], edges: list[ProposedEdge]) -> GraphDraft:
    return GraphDraft(draft_id="d1", kcs=kcs, edges=edges)


def test_valid_graph_passes() -> None:
    draft = _draft(
        [_kc("SAF.002"), _kc("SAF.003"), _kc("SAF.004")],
        [_edge("SAF.002", "SAF.003"), _edge("SAF.003", "SAF.004")],
    )
    result = validate_draft(draft)
    assert result.ok
    assert result.issues == []


def test_provenanceless_kc_rejected() -> None:
    draft = _draft([_kc("SAF.001", excerpt="   ")], [])
    result = validate_draft(draft)
    assert not result.ok
    assert [i.code for i in result.issues] == ["missing_provenance"]
    assert result.issues[0].kc_id == "SAF.001"


def test_missing_doc_id_rejected() -> None:
    draft = _draft([_kc("SAF.001", doc_id="")], [])
    result = validate_draft(draft)
    assert not result.ok
    assert result.issues[0].code == "missing_provenance"


def test_dangling_edge_rejected() -> None:
    draft = _draft([_kc("SAF.001")], [_edge("SAF.001", "SAF.999")])
    result = validate_draft(draft)
    assert not result.ok
    issue = next(i for i in result.issues if i.code == "dangling_edge")
    assert issue.edge == ("SAF.001", "SAF.999")
    assert "SAF.999" in issue.message


def test_self_loop_rejected() -> None:
    draft = _draft([_kc("SAF.001")], [_edge("SAF.001", "SAF.001")])
    result = validate_draft(draft)
    assert not result.ok
    assert result.issues[0].code == "self_loop"


def test_two_node_cycle_rejected() -> None:
    draft = _draft(
        [_kc("A"), _kc("B")],
        [_edge("A", "B"), _edge("B", "A")],
    )
    result = validate_draft(draft)
    assert not result.ok
    assert any(i.code == "cycle" for i in result.issues)


def test_three_node_cycle_rejected() -> None:
    draft = _draft(
        [_kc("A"), _kc("B"), _kc("C")],
        [_edge("A", "B"), _edge("B", "C"), _edge("C", "A")],
    )
    result = validate_draft(draft)
    assert not result.ok
    cycle = next(i for i in result.issues if i.code == "cycle")
    assert "→" in cycle.message


def test_duplicate_kc_id_rejected() -> None:
    draft = _draft([_kc("SAF.001"), _kc("SAF.001", domain="process")], [])
    result = validate_draft(draft)
    assert not result.ok
    assert any(i.code == "duplicate_kc_id" for i in result.issues)


def test_dangling_edge_does_not_crash_cycle_check() -> None:
    # An edge into an unknown node must be reported as dangling, not silently create
    # a phantom node that the cycle check then trips over.
    draft = _draft([_kc("A"), _kc("B")], [_edge("A", "B"), _edge("B", "GHOST")])
    result = validate_draft(draft)
    codes = {i.code for i in result.issues}
    assert codes == {"dangling_edge"}


def test_multiple_issues_collected() -> None:
    draft = _draft(
        [_kc("A", excerpt=""), _kc("A")],  # duplicate id + one missing provenance
        [_edge("A", "GHOST")],  # dangling
    )
    result = validate_draft(draft)
    codes = {i.code for i in result.issues}
    assert {"duplicate_kc_id", "missing_provenance", "dangling_edge"} <= codes
