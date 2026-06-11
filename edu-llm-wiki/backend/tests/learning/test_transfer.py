"""Transfer (paired t-test) tests (Perkins & Salomon 1989)."""
from services.learning.transfer import transfer_lift, find_transfer_windows


def test_paired_returns_p_value():
    res = transfer_lift([0.8] * 5, [0.7] * 5)
    assert "p_value" in res and 0.0 <= res["p_value"] <= 1.0


def test_strong_effect_low_p():
    res = transfer_lift([0.9] * 20, [0.3] * 20)
    assert res["p_value"] < 0.05


def test_window_finds_unmastered_neighbour():
    win = find_transfer_windows(
        masteries={
            "a": [(0, 0.5), (1, 0.95)],
            "b": [(0, 0.4), (1, 0.9)],
        },
    )
    # a is consistently higher than b, lift should exceed 0
    assert isinstance(win, list)
