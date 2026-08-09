from pathlib import Path

import pytest

from app.kg.loader import (
    KnowledgeComponent,
    build_digraph,
    invalidate_superseded,
    is_gated,
    load_kcs,
    unlocked_kcs,
)

GRAPH_PATH = Path(__file__).parent.parent / "app" / "kg" / "graph.yaml"


@pytest.fixture(scope="module")
def graph():
    return build_digraph(load_kcs(GRAPH_PATH))


def test_kc_with_no_prerequisites_is_unlocked(graph):
    assert not is_gated(graph, "SAF.002", {}).gated


def test_prerequisite_chain_gates_downstream_kc(graph):
    # SAF.002 -> SAF.003 -> SAF.004
    status = is_gated(graph, "SAF.003", {})
    assert status.gated
    assert status.missing_prerequisites == ["SAF.002"]

    status = is_gated(graph, "SAF.003", {"SAF.002": 0.8})
    assert not status.gated

    status = is_gated(graph, "SAF.004", {"SAF.002": 0.8, "SAF.003": 0.5})
    assert status.gated
    assert status.missing_prerequisites == ["SAF.003"]


def test_cross_document_edge_prc005_requires_saf001(graph):
    status = is_gated(graph, "PRC.005", {})
    assert status.gated
    assert "SAF.001" in status.missing_prerequisites

    status = is_gated(graph, "PRC.005", {"SAF.001": 0.9})
    assert not status.gated


def test_threshold_boundary(graph):
    assert is_gated(graph, "SAF.003", {"SAF.002": 0.7}, threshold=0.7).gated is False
    assert is_gated(graph, "SAF.003", {"SAF.002": 0.69}, threshold=0.7).gated is True


def test_campaign_scope_override_is_flagged(graph):
    status = is_gated(graph, "SAF.003", {}, campaign_scope={"SAF.003"})
    assert not status.gated
    assert status.campaign_override is True


def test_unlocked_kcs_matches_is_gated(graph):
    mastery = {"SAF.002": 0.8, "SAF.001": 0.9}
    unlocked = unlocked_kcs(graph, mastery)
    assert "SAF.003" in unlocked
    assert "SAF.004" not in unlocked
    assert "PRC.005" in unlocked


def _kc(id_: str, prereqs: list[str] | None = None, superseded_by: str | None = None):
    return KnowledgeComponent(
        id=id_,
        name=id_,
        domain="safety",
        description="d",
        prerequisites=prereqs or [],
        superseded_by_kc_id=superseded_by,
    )


def test_invalidate_superseded_drops_old_and_successor_mastery():
    kcs = [_kc("SAF.001", superseded_by="SAF.001b"), _kc("SAF.001b"), _kc("SAF.002")]
    mastery = {"SAF.001": 0.9, "SAF.001b": 0.4, "SAF.002": 0.6}
    result = invalidate_superseded(kcs, mastery)
    assert result == {"SAF.002": 0.6}


def test_invalidate_superseded_noop_when_nothing_superseded():
    kcs = [_kc("SAF.001"), _kc("SAF.002")]
    mastery = {"SAF.001": 0.9, "SAF.002": 0.6}
    assert invalidate_superseded(kcs, mastery) == mastery
