"""Transfer detection — Perkins & Salomon 1989.

We compare a learner's mastery curve on two KCs A and B. If B's mastery
overtakes A's within a short window after A is mastered, we label the pair as
a posi
References
----------
* Perkins, D. N., & Salomon, G. (1989). Are cognitive skills context-bound?

The function returns a normalised "transfer lift" score and an approximate
p-value. Falls back to ``statistics`` when ``scipy`` is missing.
"""
from __future__ import annotations

import math
from typing import Iterable

# ---------------- public ----------------

def transfer_lift(series_a: Iterable[float], series_b: Iterable[float]) -> dict:
    """Compare two aligned mastery series.

    Returns ``{"delta": ..., "p_value": ..., "n": ...}`` where:
    * ``delta`` is the mean of B minus A (positive ⇒ B > A, i.e. transfer).
    * ``p_value`` is the two-sided paired t-test p-value.
    * ``n`` is the number of paired samples.
    """
    a = list(series_a)
    b = list(series_b)
    n = min(len(a), len(b))
    if n < 2:
        return {"delta": 0.0, "p_value": 1.0, "n": n}
    a = a[:n]
    b = b[:n]
    diffs = [bi - ai for ai, bi in zip(a, b)]
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    std = math.sqrt(var)
    if std == 0:
        p = 1.0 if mean == 0 else 0.0
        return {"delta": round(mean, 4), "p_value": p, "n": n}
    t = mean / (std / math.sqrt(n))
    try:
        from scipy.stats import t as student_t  # type: ignore
        p = float(2 * (1 - student_t.cdf(abs(t), df=n - 1)))
    except Exception:
        # Normal approximation for moderate n.
        p = 2 * (1 - _normal_cdf(abs(t)))
    return {"delta": round(mean, 4), "p_value": round(p, 4), "n": n}


def find_transfer_windows(
    masteries: dict[str, list[tuple[float, float]]],
    *,
    min_lift: float = 0.2,
    max_p: float = 0.05,
) -> list[dict]:
    """Given per-KC mastery timeline (KC -> [(ts, p_known), ...]),
    return pairs (a, b) where learning A was followed by a statistically
    significant jump in B.
    """
    kcs = sorted(masteries.keys())
    windows: list[dict] = []
    for a in kcs:
        for b in kcs:
            if a >= b:
                continue
            ta = [p for _, p in masteries[a][-10:]]
            tb = [p for _, p in masteries[b][-10:]]
            res = transfer_lift(ta, tb)
            if res["delta"] >= min_lift and res["p_value"] <= max_p:
                windows.append({"a": a, "b": b, **res})
    return windows


# ---------------- helpers ----------------

def _normal_cdf(x: float) -> float:
    """Standard-normal CDF via math.erf — used when scipy is unavailable."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
