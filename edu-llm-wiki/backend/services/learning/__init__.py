"""Pedagogical learning models.

Submodules (each a thin layer of pure functions over SQLite):

* :mod:`services.learning.bkt` — Bayesian Knowledge Tracing.
* :mod:`services.learning.spaced_repetition` — SM-2 + Pimsleur early-lapse.
* :mod:`services.learning.error_model` — misconception classification.
* :mod:`services.learning.transfer` — Perkins & Salomon transfer lift.

The split keeps the cognitive models deterministic and unit-testable; the
IO wrappers (SQLite, route handlers) live in ``mastery.py`` and
``routes/learning.py``.
"""
from .bkt import observe, expected_correct, mle_fit
from .spaced_repetition import (
    sm2, next_due, quality_from_score, retention_estimate,
)
from .error_model import classify_error, top_misconception, cluster_traces
from .transfer import transfer_lift, find_transfer_windows

__all__ = [
    "observe", "expected_correct", "mle_fit",
    "sm2", "next_due", "quality_from_score", "retention_estimate",
    "classify_error", "top_misconception", "cluster_traces",
    "transfer_lift", "find_transfer_windows",
]
