"""Bayesian Knowledge Tracing (Corbett & Anderson, 1994).

Four-parameter model:
* ``p_known`` — probability that the learner currently knows the skill
* ``p_t`` — learning transition (unknown -> known per opportunity)
* ``p_g`` — guess probability when the skill is not known
* ``p_s`` — slip probability when the skill is known

The defaults are pragmatic priors for an online tutoring system. They are
intentionally conservative and are refit from a learner's observed history
by :func:`mle_fit` once enough evidence has accumulated.

References
----------
* Corbett, A. T., & Anderson, J. R. (1994). Knowledge tracing: Modeling
  the acquisition of procedural knowledge. *User Modeling and User-Adapted
  Interaction*, 4(4), 253-278.
* Yudelson, M. V., Koedinger, K. R., & Gordon, G. J. (2013). Individualized
  Bayesian knowledge tracing models. In *AIED*.
"""

from __future__ import annotations

import math
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


def _log_likelihood(items, p_known0, p_t, p_g, p_s):
    """Forward-algorithm log-likelihood of a (correct,?) sequence under BKT.

    State at time t: P(L_t = known). Observation at time t: correct in {0,1}.
    Transition: P(L_{t+1} = known) = P(L_t = known) + (1 - P(L_t = known)) * p_t.
    Emission: P(correct | L=known) = 1 - p_s; P(correct | L=not) = p_g.
    """
    if p_t <= 0 or p_t >= 1 or p_g <= 0 or p_g >= 1 or p_s <= 0 or p_s >= 1:
        return float("-inf")
    p_known = p_known0
    ll = 0.0
    for item in items:
        correct = item if isinstance(item, bool) else item[0]
        pk_known = p_known
        pk_not = 1.0 - p_known
        if correct:
            p_obs = pk_known * (1.0 - p_s) + pk_not * p_g
        else:
            p_obs = pk_known * p_s + pk_not * (1.0 - p_g)
        if p_obs <= 0:
            return float("-inf")
        ll += math.log(p_obs)
        # Update latent known-probability for next step (standard BKT learning event)
        p_known = p_known + (1.0 - p_known) * p_t
    return ll


def mle_fit(history: Iterable[tuple[bool, float]]) -> dict:
    """Maximum-likelihood estimation for a 4-parameter BKT via coordinate ascent
    on the forward-algorithm log-likelihood.

    Replaces the previous placeholder that just drifted ``p_t``/``p_g``/``p_s``
    back to the canonical prior without actually fitting data. Suitable for
    short learning sequences (~20-200 observations) typical of tutoring logs.
    """
    items = list(history)
    if not items:
        return default_params()

    # Coordinate ascent on (p_t, p_g, p_s). ``p_known`` is the initial
    # mastery; we estimate it analytically from the first observation.
    p_known0 = 0.1
    if items:
        first_correct = items[0] if isinstance(items[0], bool) else items[0][0]
        p_known0 = 0.5 if first_correct else 0.1
    p_t, p_g, p_s = 0.2, 0.2, 0.1

    # Small grid of candidate (p_t, p_g, p_s) triplets around the canonical
    # starting point. We evaluate every combination and pick the best, then
    # narrow the search around the winner.
    candidates = [round(x, 3) for x in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4]]
    best = None
    for _ in range(3):
        local_best = None
        for pt in candidates:
            for pg in candidates:
                for ps in candidates:
                    ll = _log_likelihood(items, p_known0, pt, pg, ps)
                    if local_best is None or ll > local_best[0]:
                        local_best = (ll, pt, pg, ps)
        if best is None or local_best[0] > best[0]:
            best = local_best
        # Refine: re-center the grid around the best
        best_pt, best_pg, best_ps = best[1], best[2], best[3]
        step = 0.025 if _ == 0 else 0.01
        candidates = [
            max(0.01, min(0.99, best_pt + d))
            for d in (-2 * step, -step, 0, step, 2 * step)
        ]
        candidates = [round(x, 4) for x in candidates]
    _, p_t, p_g, p_s = best

    # Also try to refine p_known0 with a small grid in [0.05, 0.5].
    best_pk = p_known0
    best_ll = _log_likelihood(items, p_known0, p_t, p_g, p_s)
    for pk in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5):
        ll = _log_likelihood(items, pk, p_t, p_g, p_s)
        if ll > best_ll:
            best_ll = ll
            best_pk = pk

    return {
        "p_known": round(max(0.01, min(0.99, best_pk)), 4),
        "p_t": round(max(0.01, min(0.99, p_t)), 4),
        "p_g": round(max(0.01, min(0.99, p_g)), 4),
        "p_s": round(max(0.01, min(0.99, p_s)), 4),
    }
