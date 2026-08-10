from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agent.tools.deliver_reply import ABSTAIN_TEXT, DeliveryMessage, deliver_reply
from app.agent.tools.fetch_remediation import RemediationReply, fetch_remediation
from app.rag.retrieve import Citation, build_index, build_index_from_sops
from app.studio.ingest import IngestedDoc

SOPS_DIR = Path(__file__).parent.parent.parent / "docs" / "sops"


@pytest.fixture
def index():
    docs = [
        IngestedDoc(
            doc_id="safety-doc",
            text="# Safety\n\n## PPE requirements\nSafety boots and hi-vis vest are "
            "mandatory in the general warehouse floor zone.\n",
        )
    ]
    return build_index(docs)


def test_fetch_remediation_returns_cited_reply_on_grounded_match(index):
    # Tiny single-doc fixture; see test_rag_retrieve.py for why the threshold is lowered.
    reply = fetch_remediation(
        index, query="what PPE is mandatory on the warehouse floor", threshold=1.0
    )
    assert reply.abstained is False
    assert reply.citation == Citation(doc_id="safety-doc", heading="PPE requirements")
    assert "Safety boots" in reply.excerpt


def test_fetch_remediation_abstains_below_threshold(index):
    reply = fetch_remediation(index, query="unrelated payroll question")
    assert reply.abstained is True
    assert reply.citation is None
    assert reply.excerpt is None
    assert reply.knowledge_gap_reason


def test_remediation_reply_rejects_missing_citation_when_not_abstained():
    with pytest.raises(ValidationError):
        RemediationReply(excerpt="some grounded-sounding claim", abstained=False, citation=None)


def test_remediation_reply_rejects_missing_excerpt_when_not_abstained():
    with pytest.raises(ValidationError):
        RemediationReply(excerpt=None, abstained=False, citation=Citation(doc_id="x", heading="y"))


def test_remediation_reply_rejects_citation_when_abstained():
    with pytest.raises(ValidationError):
        RemediationReply(
            excerpt="doesn't know",
            abstained=True,
            citation=Citation(doc_id="x", heading="y"),
        )


@pytest.fixture(scope="module")
def real_index():
    if not SOPS_DIR.is_dir():
        pytest.skip(f"docs/sops not found at {SOPS_DIR}")
    return build_index_from_sops(SOPS_DIR)


@pytest.mark.parametrize(
    "query",
    [
        "what PPE is required in the dangerous goods segregation area",
        "how do I execute a safe lift for a heavy or awkward load",
        "what is the pedestrian right of way rule around MHE",
        "limited quantity versus excepted quantity dangerous goods",
    ],
)
def test_every_non_abstaining_remediation_on_real_corpus_carries_a_citation(real_index, query):
    reply = fetch_remediation(real_index, query=query)
    if not reply.abstained:
        assert reply.citation is not None
        assert reply.excerpt is not None


def test_off_corpus_question_on_real_corpus_abstains(real_index):
    reply = fetch_remediation(
        real_index, query="what is the company's payroll direct deposit cutoff"
    )
    assert reply.abstained is True
    assert reply.citation is None
    assert reply.excerpt is None


# --- paraphrase composition (app/agent/tools/deliver_reply/__init__.py) -------------


class _ParaphrasingLLM:
    """Stands in for the paraphrase-composing LLM: returns a rewording of the
    excerpt rather than quoting it verbatim, to prove `ComposedDelivery.citation`
    stays Python-set regardless of what the generated prose says."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def extract(self, output_model, system, user):
        assert output_model is DeliveryMessage
        return DeliveryMessage(text=self._text)


async def test_deliver_reply_paraphrases_and_keeps_citation_structural():
    citation = Citation(doc_id="safety-doc", heading="PPE requirements")
    excerpt = "Safety boots and hi-vis vest are mandatory in the general warehouse floor zone."
    llm = _ParaphrasingLLM(
        "You'll need steel-toe boots and a high-visibility vest before you're on the "
        "warehouse floor — it's a hard requirement, per the PPE requirements SOP."
    )

    delivery = await deliver_reply(
        llm,
        language="en",
        sentiment="neutral",
        fallback_text=f"{excerpt}\n\n— {citation.doc_id}",
        excerpt=excerpt,
        citation=citation,
    )

    # The prose paraphrases (doesn't quote "Safety boots and hi-vis vest" verbatim)...
    assert "Safety boots and hi-vis vest" not in delivery.text
    # ...but the citation is Python-set from what the caller passed in, never parsed
    # out of the LLM's own text.
    assert delivery.citation == citation


async def test_deliver_reply_flags_low_groundedness_without_blocking():
    citation = Citation(doc_id="safety-doc", heading="PPE requirements")
    excerpt = "Safety boots and hi-vis vest are mandatory in the general warehouse floor zone."
    # Deliberately unrelated to the excerpt, to trip the groundedness floor.
    llm = _ParaphrasingLLM("Remember to submit your timesheet by Friday.")

    delivery = await deliver_reply(
        llm,
        language="en",
        sentiment="neutral",
        fallback_text=ABSTAIN_TEXT,
        excerpt=excerpt,
        citation=citation,
    )

    assert delivery.groundedness_warning is True
    # Fail-open on UX: the (ungrounded-looking) text still gets delivered.
    assert delivery.text == "Remember to submit your timesheet by Friday."
