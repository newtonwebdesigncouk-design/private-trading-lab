"""Audited indicator edge cases."""

import pytest

from app.indicators import highest, mean, momentum, standard_deviation, zscore


def test_indicators_use_only_trailing_values() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert mean(values, 2) == 3.5
    assert momentum(values, 2) == 1.0
    assert highest(values, 2, exclude_current=True) == 3.0
    assert standard_deviation(values, 2) == 0.5
    assert zscore(values, 2) == 1.0


def test_indicators_require_valid_windows() -> None:
    with pytest.raises(ValueError):
        mean([1.0], 0)
    assert momentum([1.0], 2) is None
