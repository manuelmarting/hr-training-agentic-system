import pytest

from app.agent.tools.extract_facts.pii_gate import gate, pattern_check
from app.schemas.extraction import PersonalFact


def _fact(fact_type="preferred_name", value="Ana"):
    return PersonalFact(fact_type=fact_type, value=value, confidence=0.9)


@pytest.mark.parametrize(
    "value",
    [
        "I was just diagnosed with diabetes",
        "I'm on dialysis three times a week",
        "I'm Muslim and need Friday prayer time",
        "My ethnicity is important to me",
        "I'm a union member and shop steward",
        "I'm gay and my partner works nights too",
        "The system needs a fingerprint scan",
    ],
)
def test_pattern_check_rejects_special_category_values(value):
    result = pattern_check(_fact(value=value))
    assert result.allowed is False
    assert result.stage == "pattern"


@pytest.mark.parametrize(
    "fact_type,value",
    [
        ("preferred_name", "Ana"),
        ("preferred_language", "es"),
        ("shift_pattern", "mornings only"),
        ("contact_time_preference", "after 6pm"),
    ],
)
def test_pattern_check_allows_each_allowlisted_type(fact_type, value):
    result = pattern_check(_fact(fact_type=fact_type, value=value))
    assert result.allowed is True


def test_gate_stores_only_when_both_stages_pass():
    result = gate(_fact(), llm_verdict=True)
    assert result.allowed is True
    assert result.stage == "combined"


def test_gate_rejects_when_pattern_fails_even_if_llm_passes():
    result = gate(_fact(value="I have cancer"), llm_verdict=True)
    assert result.allowed is False
    assert result.stage == "pattern"


def test_gate_rejects_when_llm_fails_even_if_pattern_passes():
    result = gate(_fact(), llm_verdict=False)
    assert result.allowed is False
    assert result.stage == "llm"


def test_gate_fails_closed_on_llm_error():
    result = gate(_fact(), llm_verdict=None)
    assert result.allowed is False
    assert result.stage == "llm"
