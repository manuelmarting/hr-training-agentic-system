from pathlib import Path

import pytest

from app.rag.retrieve import (
    Abstain,
    Grounded,
    build_index,
    build_index_from_sops,
    chunk_document,
    retrieve,
)
from app.studio.ingest import IngestedDoc

SOPS_DIR = Path(__file__).parent.parent.parent / "docs" / "sops"


def _doc(doc_id: str, text: str) -> IngestedDoc:
    return IngestedDoc(doc_id=doc_id, text=text)


# --- chunking (synthetic fixture, no filesystem dependency) -----------------


def test_chunk_document_splits_on_level_two_headings():
    doc = _doc(
        "demo",
        "# Title\nmeta line\n\n## Section A\nbody A\n\n## Section B\nbody B\n",
    )
    chunks = chunk_document(doc)
    headings = [c.heading for c in chunks]
    assert headings == ["Title", "Section A", "Section B"]
    assert "body A" in chunks[1].text
    assert "body B" in chunks[2].text


def test_chunk_document_no_headings_is_single_chunk():
    doc = _doc("demo", "just some prose with no headings at all")
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].doc_id == "demo"


# --- retrieval on a synthetic corpus -----------------------------------------


@pytest.fixture
def synthetic_index():
    docs = [
        _doc(
            "safety-doc",
            "# Safety\n\n## PPE requirements\nSafety boots and hi-vis vest are mandatory "
            "in the general warehouse floor zone.\n\n## Manual handling\nBend at the knees, "
            "not the waist, when lifting any load.\n",
        ),
        _doc(
            "dg-doc",
            "# Dangerous goods\n\n## Limited quantity thresholds\nLimited-quantity and "
            "excepted-quantity thresholds must not be confused when declaring dangerous "
            "goods shipments.\n",
        ),
    ]
    return build_index(docs)


def test_retrieve_returns_grounded_result_for_on_corpus_query(synthetic_index):
    # A tiny 2-document fixture sits on a different BM25 score scale than the real
    # 8-doc corpus DEFAULT_THRESHOLD is calibrated against, so use a low threshold here.
    outcome = retrieve(
        synthetic_index, "what PPE is mandatory on the warehouse floor", threshold=1.0
    )
    assert isinstance(outcome, Grounded)
    assert outcome.citation.doc_id == "safety-doc"
    assert outcome.citation.heading == "PPE requirements"


def test_retrieve_abstains_for_off_corpus_query(synthetic_index):
    outcome = retrieve(synthetic_index, "what is the payroll direct deposit schedule")
    assert isinstance(outcome, Abstain)
    assert outcome.reason


def test_retrieve_threshold_is_tunable(synthetic_index):
    # An absurdly high threshold forces abstain even on a good match.
    outcome = retrieve(synthetic_index, "PPE requirements warehouse floor", threshold=1000.0)
    assert isinstance(outcome, Abstain)


# --- retrieval on the real docs/sops/ corpus (plan §4 Phase 3 exit criteria) --


@pytest.fixture(scope="module")
def real_index():
    if not SOPS_DIR.is_dir():
        pytest.skip(f"docs/sops not found at {SOPS_DIR}")
    return build_index_from_sops(SOPS_DIR)


def test_real_corpus_on_topic_question_is_grounded_with_citation(real_index):
    outcome = retrieve(real_index, "what PPE is required in the dangerous goods segregation area")
    assert isinstance(outcome, Grounded)
    assert outcome.citation.doc_id
    assert outcome.citation.heading


def test_real_corpus_off_corpus_question_abstains(real_index):
    outcome = retrieve(real_index, "what is the company's payroll direct deposit cutoff date")
    assert isinstance(outcome, Abstain)


def test_real_corpus_dangerous_goods_misconception_is_grounded(real_index):
    outcome = retrieve(real_index, "limited quantity versus excepted quantity dangerous goods")
    assert isinstance(outcome, Grounded)
    assert outcome.citation.doc_id == "06-picking-packing-dg-coldchain"
