"""Extraction pipeline tests (plan §8): ingest, reconcile, and stubbed pass A/B."""

import re

import pytest

from app.agent.llm import StructuredLLM, StructuredLLMError
from app.studio.extract import extract_graph
from app.studio.extract_schemas import (
    DocKCProposal,
    EdgeProposal,
    ExtractedEdge,
    ExtractedKC,
)
from app.studio.ingest import IngestedDoc, UnsupportedDocumentError, ingest
from app.studio.reconcile import normalize_name, reconcile

# --- Stub LLM -------------------------------------------------------------


class StubLLM:
    """Satisfies the StructuredLLM protocol deterministically, keyed off the prompt."""

    def __init__(
        self,
        doc_map: dict[str, DocKCProposal],
        edges: EdgeProposal | None = None,
        *,
        fail_docs: set[str] = frozenset(),
        fail_edges: bool = False,
    ) -> None:
        self.doc_map = doc_map
        self.edges = edges or EdgeProposal()
        self.fail_docs = set(fail_docs)
        self.fail_edges = fail_edges

    async def extract(self, output_model, system, user):  # type: ignore[no-untyped-def]
        if output_model is DocKCProposal:
            doc_id = re.search(r'id="([^"]+)"', user).group(1)
            if doc_id in self.fail_docs:
                raise StructuredLLMError("pass A boom")
            return self.doc_map.get(doc_id, DocKCProposal())
        if output_model is EdgeProposal:
            if self.fail_edges:
                raise StructuredLLMError("pass B boom")
            return self.edges
        raise AssertionError(f"unexpected output_model {output_model}")

    async def acall_with_tools(self, messages, tools):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def _ek(name: str, domain: str = "safety") -> ExtractedKC:
    return ExtractedKC(
        name=name, domain=domain, description="desc", heading="h", excerpt="verbatim"
    )


def test_stub_satisfies_protocol() -> None:
    assert isinstance(StubLLM({}), StructuredLLM)


# --- ingest ---------------------------------------------------------------


def test_ingest_markdown() -> None:
    doc = ingest("06-picking-packing-dg-coldchain.md", b"# Heading\nbody")
    assert doc.doc_id == "06-picking-packing-dg-coldchain"
    assert "body" in doc.text


def test_ingest_unsupported_type() -> None:
    with pytest.raises(UnsupportedDocumentError):
        ingest("data.xlsx", b"...")


# --- reconcile ------------------------------------------------------------


def test_reconcile_dedupes_across_docs_and_merges_misconceptions() -> None:
    a = _ek("Manual handling principles")
    a.known_misconceptions = ["lift with your back"]
    b = _ek("manual   handling PRINCIPLES")  # same normalized name
    b.known_misconceptions = ["no warm-up needed"]
    kcs = reconcile({"01": [a], "02": [b]})
    assert len(kcs) == 1
    assert set(kcs[0].known_misconceptions) == {"lift with your back", "no warm-up needed"}


def test_reconcile_assigns_ids_deterministically() -> None:
    proposals = {
        "01": [_ek("PPE selection", "safety"), _ek("Manual handling", "safety")],
        "02": [_ek("Reach truck limits", "equipment")],
    }
    first = {kc.name: kc.id for kc in reconcile(proposals)}
    second = {kc.name: kc.id for kc in reconcile(proposals)}
    assert first == second
    assert first["PPE selection"] == "SAF.001"
    assert first["Manual handling"] == "SAF.002"
    assert first["Reach truck limits"] == "EQP.001"


def test_reconcile_reuses_seed_id_and_reserves_number() -> None:
    seed_ids = {normalize_name("PPE selection and correct use per zone"): "SAF.001"}
    proposals = {
        "01": [
            _ek("Brand new safety topic", "safety"),  # fresh — must skip reserved 001
            _ek("PPE selection and correct use per zone", "safety"),  # reuses SAF.001
        ]
    }
    ids = {kc.name: kc.id for kc in reconcile(proposals, seed_ids)}
    assert ids["PPE selection and correct use per zone"] == "SAF.001"
    assert ids["Brand new safety topic"] == "SAF.002"


# --- extract_graph (pass A + reconcile + pass B) --------------------------


@pytest.mark.asyncio
async def test_extract_graph_builds_draft_with_edges() -> None:
    docs = [IngestedDoc(doc_id="01", text="lifting rules")]
    doc_map = {
        "01": DocKCProposal(kcs=[_ek("Safe lift execution"), _ek("Manual handling principles")])
    }
    # reconcile assigns SAF.001 (safe lift), SAF.002 (manual handling) in encounter order
    edges = EdgeProposal(
        edges=[
            ExtractedEdge(
                source_kc_id="SAF.002", target_kc_id="SAF.001", rationale="principles first"
            )
        ]
    )
    draft = await extract_graph(StubLLM(doc_map, edges), docs, draft_id="d1")

    assert draft.draft_id == "d1"
    assert {kc.id for kc in draft.kcs} == {"SAF.001", "SAF.002"}
    assert all(kc.origin == "extracted" for kc in draft.kcs)
    assert draft.kcs[0].provenance.doc_id == "01"
    assert [(e.source_kc_id, e.target_kc_id) for e in draft.edges] == [("SAF.002", "SAF.001")]


@pytest.mark.asyncio
async def test_extract_drops_hallucinated_edge_endpoints() -> None:
    docs = [IngestedDoc(doc_id="01", text="x")]
    doc_map = {"01": DocKCProposal(kcs=[_ek("A"), _ek("B")])}
    edges = EdgeProposal(
        edges=[
            ExtractedEdge(source_kc_id="SAF.001", target_kc_id="SAF.999", rationale="ghost"),
            ExtractedEdge(source_kc_id="SAF.001", target_kc_id="SAF.002", rationale="real"),
        ]
    )
    draft = await extract_graph(StubLLM(doc_map, edges), docs)
    assert [(e.source_kc_id, e.target_kc_id) for e in draft.edges] == [("SAF.001", "SAF.002")]


@pytest.mark.asyncio
async def test_extract_pass_a_failure_skips_document() -> None:
    docs = [IngestedDoc(doc_id="01", text="x"), IngestedDoc(doc_id="02", text="y")]
    doc_map = {
        "01": DocKCProposal(kcs=[_ek("A")]),
        "02": DocKCProposal(kcs=[_ek("B")]),
    }
    draft = await extract_graph(StubLLM(doc_map, fail_docs={"02"}), docs)
    assert [kc.name for kc in draft.kcs] == ["A"]  # doc 02 fell back to empty


@pytest.mark.asyncio
async def test_extract_pass_b_failure_yields_no_edges() -> None:
    docs = [IngestedDoc(doc_id="01", text="x")]
    doc_map = {"01": DocKCProposal(kcs=[_ek("A"), _ek("B")])}
    draft = await extract_graph(StubLLM(doc_map, fail_edges=True), docs)
    assert len(draft.kcs) == 2
    assert draft.edges == []
