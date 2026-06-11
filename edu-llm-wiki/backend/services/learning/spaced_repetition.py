"""Spaced repetition scheduler — SM-2 with Pimsleur early-lapse rule.

References
----------
* Wozniak, P. (1985) — "Optimization of repetition spacing in the practice of learning"
* Pimsleur, P. (1967) — "A memory schedule"

We follow Wozniak's modern interpretation of the SM-2 algorithm: ease factor
starts at 2.5 and is adjusted by response quality (0..5). Interval doubles
on q>=3, resets to 1 on q<3, and we floor the next due at 1 hour so a lapse
does not cause an immediate retrigger of the same card.

Retention estimate uses the Ebbinghaus approximation: R = exp(-t / stability)
where ``stability`` is approximated by the current ease factor (days).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


MIN_INTERVAL_SECONDS = 3600.0  # 1h floor to prevent lapses retriggering immediately.


@dataclass(frozen=True)
class SM2Result:
    ease_factor: float
    interval_seconds: float
    repetitions: int


def quality_from_score(score: float, *, max_score: float = 1.0) -> int:
    """Map a continuous score in [0, max_score] to SM-2 quality in 0..5.

    The mapping is intentionally coarse: 0..2 = lapse, 3 = correct-with-effort,
    4 = correct, 5 = easy. The thresholds follow Wozniak's guideline.
    """
    if max_score <= 0:
        return 0
    pct = max(0.0, min(1.0, score / max_score))
    if pct < 0.3:
        return 0
    if pct < 0.5:
        return 2
    if pct < 0.7:
        return 3
    if pct < 0.9:
        return 4
    return 5


def sm2(quality: int, prev_ease: float, prev_interval: float, prev_reps: int) -> SM2Result:
    """One SM-2 update step. Pure function — no I/O, no side effects."""
    q = max(0, min(5, int(quality)))
    ease = float(prev_ease)
    reps = int(prev_reps)
    interval = float(prev_interval)

    # Update ease factor
    ease = max(1.3, ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))

    # Update repetition counter and interval
    if q < 3:
        reps = 0
        interval = MIN_INTERVAL_SECONDS  # 1h — see module docstring
    else:
        reps += 1
        if reps == 1:
            interval = 24 * 3600.0  # 1 day
        elif reps == 2:
            interval = 6 * 24 * 3600.0  # 6 days
        else:
            interval = max(interval, 1.0) * ease
            # Pimsleur early-lapse: cap growth on the third repetition
            if reps == 3:
                interval = min(interval, 14 * 24 * 3600.0)

    interval = max(interval, MIN_INTERVAL_SECONDS)
    return SM2Result(ease_factor=ease, interval_seconds=interval, repetitions=reps)


def next_due(now_epoch: float, interval_seconds: float) -> float:
    return float(now_epoch) + float(interval_seconds)


def retention_estimate(elapsed_seconds: float, ease_factor: float) -> float:
    """Ebbinghaus: R = exp(-t / S). Stability approximated by ease in days."""
    stability_days = max(1e-3, float(ease_factor))
    stability = stability_days * 24 * 3600.0
    retention = math.exp(-max(0.0, float(elapsed_seconds)) / stability)
    return float(retention)
