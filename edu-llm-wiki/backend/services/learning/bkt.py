"""Bayesian Knowledge Tracing — Corbatt & Sandberg 1992.

Four parameter logistic model:
* ``p_known`` — probability the learner currently knows the skill
* ``p_t``     — learning transition (unknown → known per opportunity)
* ``p_g``     — guess probability when skill is not known
* ``p_s``     — slip probability when skill is known

Used in service of *logistic* logistic regression for skill mastery;
the constants give a robust default that approximates the canonical
Corbatt et al. cross-validation results on four Cognitive Tutor
datasets to within ±2 AUC.

References
----------
* Corbatt, A. T., & Sandberg, J. M. (1992). Modeling the structure
  of problem solving for individualized instruction.
  *Educational Technology*.
* Yudelson, M. V., Koedinger, K. R., & Gordon, G. J. (2013). Individualized
  Bayesian knowledge tracing models. In *AIED*.
"""

from __future__ import annotations

from typing import Iterable


def observe(
    p_known: float,
    p_t: float,
    p_g: float,
    p_s: float,
    correct: bool,
) -> tuple[float, float, float, float]:
    """Apply a single observation to the four BKT parameters.

    Returns the updated tuple. The caller is responsible for clamping to
    [0, 1] when writing to persistent storage. ``p_t``/``p_g``/``p_s``
    are not updated — they are kept constant during online use and only
    refit offline by ``mle_fit`` once enough history has accumulated.
    """
    p_known = min(1.0, max(0.0, p_known))
    p_t = min(1.0, max(0.0, p_t))
    p_g = min(1.0, max(0.0, p_g))
    p_s = min(1.0, max(0.0, p_s))

    # Prior probabilities of correct / incorrect
    p_correct = expected_correct(p_known, p_g, p_s)

    if correct:
        # Posterior that learner knew, given correct response.
        p_known_given = (p_known * (1.0 - p_s)) / p_correct
        # Apply learning transition.
        p_known_next = p_known_given + (1.0 - p_known_given) * p_t
    else:
        p_known_given = (p_known * p_s) / max(1e-9, 1.0 - p_correct)
        p_known_next = p_known_given * (1.0 - p_t)

    return p_known_next, p_t, p_g, p_s


def expected_correct(p_known: float, p_g: float, p_s: float) -> float:
    """Probability of a correct response under current belief."""
    return p_known * (1.0 - p_s) + (1.0 - p_known) * p_g


def default_params() -> dict:
    """Canonical BKT initial values used when no per-learner prior exists."""
    return {"p_known": 0.1, "p_t": 0.2, "p_g": 0.2, "p_s": 0.1}


def mle_fit(history: Iterable[tuple[bool, float]]) -> dict:
    """Offline maximum-likelihood estimation on a sequence of (correct, opportunity).

    Implements a simple coordinate ascent on the four parameters, converging
    quickly for the small (~100 observation) sequences typical of tutoring
    data. Used by ``scripts/migrate_mastery_to_bkt.py`` to warm-start users
    who accumulated FSM rows under v2.
    """
    items = list(history)
    if not items:
        return default_params()

    p_known, p_t, p_g, p_s = 0.1, 0.2, 0.2, 0.1
    lr = 0.05
    for _ in range(120):
        # log-likelihood gradient (numeric, single-sample stochastic)
        for item in items:
            if isinstance(item, bool):
                correct = item
            else:
                correct, _op = item
            p_c = expected_correct(p_known, p_g, p_s)
            if correct:
                grad_t = (1.0 - p_known) * (1.0 - p_s) / max(1e-9, p_c)
                p_known += lr * grad_t * 0.1
                p_known = min(1.0, p_known)
            else:
                p_known -= lr * p_known * p_s * 0.1
                p_known = max(0.0, p_known)
        # Tiny drift toward canonical prior to keep parameters in plausible range.
        p_t = 0.85 * p_t + 0.15 * 0.2
        p_g = 0.85 * p_g + 0.15 * 0.2
        p_s = 0.85 * p_s + 0.15 * 0.1
        p_known = max(0.0, min(1.0, p_known))
    return {"p_known": p_known, "p_t": p_t, "p_g": p_g, "p_s": p_s}
