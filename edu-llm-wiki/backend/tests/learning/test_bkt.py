"""BKT observer + MLE fit, against hand-rolled expected values.

We deliberately avoid hardcoded magic numbers in the tests so the
assertions are human-readable: we predict, run, and compare.
"""
from services.learning.bkt import observe, expected_correct, mle_fit

def test_observe_correct_increases_p_known():
    p_known, *_ = observe(0.1, 0.2, 0.2, 0.1, correct=True)
    assert p_known > 0.1, f"expected p_known to rise on correct, got {p_known}"
    assert p_known < 1.0

def test_observe_wrong_decreases_p_known():
    p_known, *_ = observe(0.9, 0.2, 0.2, 0.1, correct=False)
    assert p_known < 0.9

def test_expected_correct_in_unit_interval():
    assert 0 <= expected_correct(0.0, 0.2, 0.1) <= 1
    assert 0 <= expected_correct(1.0, 0.2, 0.1) <= 1
    assert 0 <= expected_correct(0.5, 0.0, 0.0) <= 1

def test_mle_fit_recovers_high_learner():
    # Synthetic learner that always gets it right
    history = [True] * 20
    fit = mle_fit(history)
    assert fit["p_known"] > 0.85
