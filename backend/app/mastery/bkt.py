"""Bayesian Knowledge Tracing — pure functions, no I/O, no LLM (PRD §7, CLAUDE.md).

Every mastery number the agent ever shows or gates on is produced here from an
explicit observation. The LLM never computes a probability; it only classifies an
answer as correct/incorrect/partial (`app/schemas/extraction.TurnEvaluation`), and
that classification is the sole input to `update()`.

Standard BKT: four parameters per KC —
  p_init  — prior probability of already knowing the KC
  p_learn — probability of transitioning from unknown to known after this turn
  p_slip  — probability of answering incorrectly despite knowing it
  p_guess — probability of answering correctly despite not knowing it
"""

from dataclasses import dataclass
from typing import Literal

Observation = Literal["correct", "incorrect", "partial"]


@dataclass(frozen=True)
class BKTParams:
    p_init: float = 0.3
    p_learn: float = 0.15
    p_slip: float = 0.1
    p_guess: float = 0.2


DEFAULT_PARAMS = BKTParams()

# Decay: mastery drifts back toward the prior over elapsed time (per-day rate).
DEFAULT_DECAY_RATE = 0.01


def update(prior: float, observation: Observation, params: BKTParams = DEFAULT_PARAMS) -> float:
    """One BKT posterior update from a single observation.

    `partial` is treated as half-weight evidence: it blends the correct- and
    incorrect-conditioned posteriors evenly, since a partially-correct answer is
    real but weaker evidence of mastery than a fully correct one.
    """
    if not 0.0 <= prior <= 1.0:
        raise ValueError(f"prior must be in [0, 1], got {prior}")

    if observation == "correct":
        posterior = _posterior_given_correct(prior, params)
    elif observation == "incorrect":
        posterior = _posterior_given_incorrect(prior, params)
    else:  # partial
        posterior = (
            _posterior_given_correct(prior, params) + _posterior_given_incorrect(prior, params)
        ) / 2

    # Learning transition: even if not known yet, this turn may have taught it.
    return posterior + (1 - posterior) * params.p_learn


def decay(mastery: float, days_elapsed: float, rate: float = DEFAULT_DECAY_RATE) -> float:
    """Drift mastery back toward `p_init` as time passes without reinforcement."""
    if days_elapsed < 0:
        raise ValueError(f"days_elapsed must be >= 0, got {days_elapsed}")
    factor = max(0.0, 1 - rate * days_elapsed)
    return DEFAULT_PARAMS.p_init + (mastery - DEFAULT_PARAMS.p_init) * factor


def seed_from_prior(source: Literal["induction", "campaign", "manual"], value: float) -> float:
    """Validate and pass through an externally-sourced mastery seed (e.g. Maria's prior).

    Deliberately not a lookup table — the value always comes from the external system;
    this only enforces the [0, 1] invariant so a bad upstream value can't corrupt state.
    """
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"seed value must be in [0, 1], got {value} (source={source})")
    return value


def _posterior_given_correct(prior: float, params: BKTParams) -> float:
    p_correct = prior * (1 - params.p_slip) + (1 - prior) * params.p_guess
    if p_correct == 0:
        return prior
    return prior * (1 - params.p_slip) / p_correct


def _posterior_given_incorrect(prior: float, params: BKTParams) -> float:
    p_incorrect = prior * params.p_slip + (1 - prior) * (1 - params.p_guess)
    if p_incorrect == 0:
        return prior
    return prior * params.p_slip / p_incorrect
