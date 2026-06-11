"""Spaced repetition / SM-2 invariants (Wozniak 1985)."""
from services.learning.spaced_repetition import sm2, next_due, quality_from_score


def test_sm2_quality_5_first_correct():
    r = sm2(quality=5, prev_ease=2.5, prev_interval=0, prev_reps=0)
    assert r.repetitions == 1
    assert r.interval_seconds >= 86_400
    assert r.ease_factor >= 2.5


def test_sm2_quality_0_resets():
    r = sm2(quality=0, prev_ease=2.5, prev_interval=10, prev_reps=3)
    assert r.repetitions == 0
    assert r.ease_factor < 2.5


def test_quality_from_score_monotone():
    assert quality_from_score(0.95) >= quality_from_score(0.5) >= quality_from_score(0.1)
    assert quality_from_score(0.0) == 0
    assert quality_from_score(1.0) == 5


def test_next_due_in_future():
    due = next_due(now_epoch=1_000_000.0, interval_seconds=3600)
    assert due > 1_000_000.0
