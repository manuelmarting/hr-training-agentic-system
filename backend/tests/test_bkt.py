import pytest

from app.mastery.bkt import BKTParams, decay, seed_from_prior, update


def test_correct_answer_increases_mastery():
    posterior = update(0.3, "correct")
    assert posterior > 0.3


def test_incorrect_answer_decreases_mastery():
    posterior = update(0.5, "incorrect")
    assert posterior < 0.5


def test_partial_is_between_correct_and_incorrect():
    prior = 0.4
    correct = update(prior, "correct")
    incorrect = update(prior, "incorrect")
    partial = update(prior, "partial")
    assert incorrect < partial < correct


def test_posterior_bounded_in_unit_interval():
    for obs in ("correct", "incorrect", "partial"):
        posterior = update(0.5, obs)
        assert 0.0 <= posterior <= 1.0


def test_repeated_correct_observations_monotonically_increase_then_saturate():
    p = 0.1
    prev = p
    for _ in range(20):
        p = update(p, "correct")
        assert p >= prev
        prev = p
    assert p > 0.9


def test_invalid_prior_raises():
    with pytest.raises(ValueError):
        update(1.5, "correct")
    with pytest.raises(ValueError):
        update(-0.1, "correct")


def test_slip_and_guess_bounds_respected():
    # With slip=0, a correct answer from a fully-known state can't push posterior down.
    params = BKTParams(p_init=0.3, p_learn=0.0, p_slip=0.0, p_guess=0.0)
    posterior = update(0.9, "correct", params)
    assert posterior >= 0.9


def test_decay_moves_toward_prior_over_time():
    mastery = 0.9
    decayed = decay(mastery, days_elapsed=30)
    assert decayed < mastery
    assert decayed > BKTParams().p_init


def test_decay_zero_days_is_noop():
    assert decay(0.7, days_elapsed=0) == pytest.approx(0.7)


def test_decay_negative_days_raises():
    with pytest.raises(ValueError):
        decay(0.5, days_elapsed=-1)


def test_seed_from_prior_valid():
    assert seed_from_prior("induction", 0.6) == 0.6


def test_seed_from_prior_out_of_range_raises():
    with pytest.raises(ValueError):
        seed_from_prior("induction", 1.2)


def test_replay_is_idempotent():
    """Replaying the same observation sequence from the same start yields the same end state."""
    observations = ["correct", "incorrect", "correct", "partial", "correct"]

    def run(start: float) -> float:
        p = start
        for obs in observations:
            p = update(p, obs)
        return p

    assert run(0.3) == pytest.approx(run(0.3))
