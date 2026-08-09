"""Unit tests for the studio draft repo (plan §8: CRUD round-trip)."""

import pytest

from app.studio.repo import DraftNotFoundError, DraftRepo
from app.studio.schemas import DraftStatus, GraphDraft, ProposedKC, Provenance


def _draft(draft_id: str = "d1") -> GraphDraft:
    return GraphDraft(
        draft_id=draft_id,
        source_docs=["01-ppe-manual-handling"],
        kcs=[
            ProposedKC(
                id="SAF.001",
                name="PPE selection",
                domain="safety",
                description="Select PPE per zone.",
                regulation=None,
                known_misconceptions=["gloves are optional in the DG bay"],
                provenance=Provenance(
                    doc_id="01-ppe-manual-handling",
                    heading="1. PPE",
                    excerpt="Wear the PPE specified for the zone.",
                ),
                origin="extracted",
            )
        ],
    )


@pytest.fixture
def repo() -> DraftRepo:
    r = DraftRepo(":memory:")
    yield r
    r.close()


def test_create_and_get_round_trip(repo: DraftRepo) -> None:
    original = _draft()
    repo.create(original)
    loaded = repo.get("d1")
    assert loaded == original
    assert loaded.kcs[0].known_misconceptions == ["gloves are optional in the DG bay"]


def test_get_missing_raises(repo: DraftRepo) -> None:
    with pytest.raises(DraftNotFoundError):
        repo.get("nope")


def test_get_or_none(repo: DraftRepo) -> None:
    assert repo.get_or_none("nope") is None
    repo.create(_draft())
    assert repo.get_or_none("d1") is not None


def test_create_duplicate_id_raises(repo: DraftRepo) -> None:
    repo.create(_draft())
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        repo.create(_draft())


def test_save_upserts(repo: DraftRepo) -> None:
    repo.create(_draft())
    draft = repo.get("d1")
    draft.kcs[0].name = "PPE selection and correct use per zone"
    draft.kcs[0].origin = "edited"
    repo.save(draft)
    reloaded = repo.get("d1")
    assert reloaded.kcs[0].name == "PPE selection and correct use per zone"
    assert reloaded.kcs[0].origin == "edited"


def test_set_status(repo: DraftRepo) -> None:
    repo.create(_draft())
    repo.set_status("d1", DraftStatus.APPROVED)
    assert repo.get("d1").status == DraftStatus.APPROVED


def test_delete(repo: DraftRepo) -> None:
    repo.create(_draft())
    repo.delete("d1")
    assert repo.get_or_none("d1") is None
    with pytest.raises(DraftNotFoundError):
        repo.delete("d1")


def test_list_drafts(repo: DraftRepo) -> None:
    repo.create(_draft("a"))
    repo.create(_draft("b"))
    ids = {d.draft_id for d in repo.list_drafts()}
    assert ids == {"a", "b"}
