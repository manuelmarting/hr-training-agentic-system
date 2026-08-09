import pytest

from app.persistence.repo import FactNotFoundError, Repo
from app.schemas.extraction import PersonalFact, SessionSummary


@pytest.fixture
def repo():
    r = Repo(":memory:")
    yield r
    r.close()


def test_upsert_and_get_mastery(repo):
    repo.upsert_mastery("emp-1", "SAF.001", 0.4)
    repo.upsert_mastery("emp-1", "SAF.001", 0.7)  # overwrite
    repo.upsert_mastery("emp-1", "SAF.002", 0.2)
    assert repo.get_mastery("emp-1") == {"SAF.001": 0.7, "SAF.002": 0.2}


def test_get_mastery_empty_for_unknown_employee(repo):
    assert repo.get_mastery("nobody") == {}


def test_add_list_delete_fact(repo):
    fact = PersonalFact(fact_type="preferred_language", value="es", confidence=0.95)
    stored = repo.add_fact("emp-1", fact)
    assert stored.id > 0

    facts = repo.list_facts("emp-1")
    assert len(facts) == 1
    assert facts[0].fact.value == "es"

    repo.delete_fact(stored.id)
    assert repo.list_facts("emp-1") == []


def test_delete_unknown_fact_raises(repo):
    with pytest.raises(FactNotFoundError):
        repo.delete_fact(999)


def test_archive_session_write_once(repo):
    summary = SessionSummary(session_id="sess-1", mastery_deltas={"SAF.001": 0.3})
    repo.archive_session("emp-1", summary)
    fetched = repo.get_archived_session("sess-1")
    assert fetched is not None
    assert fetched.mastery_deltas == {"SAF.001": 0.3}
    assert fetched.not_for_use_in == ["performance_management", "termination"]


def test_get_archived_session_missing_returns_none(repo):
    assert repo.get_archived_session("nope") is None


def test_append_and_list_events_ordered(repo):
    payload = {"kc_id": "SAF.001", "classification": "correct"}
    repo.append_event("sess-1", 0, "turn_evaluated", payload)
    repo.append_event("sess-1", 1, "mastery_update", {"kc_id": "SAF.001", "posterior": 0.6})
    events = repo.list_events("sess-1")
    assert [e.event_type for e in events] == ["turn_evaluated", "mastery_update"]
    assert events[0].payload["kc_id"] == "SAF.001"


def test_events_scoped_per_session(repo):
    repo.append_event("sess-1", 0, "turn_evaluated", {})
    repo.append_event("sess-2", 0, "turn_evaluated", {})
    assert len(repo.list_events("sess-1")) == 1
    assert len(repo.list_events("sess-2")) == 1
