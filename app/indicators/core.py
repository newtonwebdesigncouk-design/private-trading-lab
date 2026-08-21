"""Indicators accept only the history explicitly passed by the strategy."""

import math
from collections.abc import Sequence


def mean(values: Sequence[float], window: int) -> float | None:
    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def standard_deviation(values: Sequence[float], window: int) -> float | None:
    average = mean(values, window)
    if average is None:
        return None
    variance = sum((value - average) ** 2 for value in values[-window:]) / window
    return math.sqrt(variance)


def momentum(values: Sequence[float], lookback: int) -> float | None:
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    if len(values) <= lookback:
        return None
    return values[-1] / values[-lookback - 1] - 1.0


def highest(values: Sequence[float], window: int, *, exclude_current: bool = False) -> float | None:
    source = values[:-1] if exclude_current else values
    if window <= 0:
        raise ValueError("window must be positive")
    if len(source) < window:
        return None
    return max(source[-window:])


def zscore(values: Sequence[float], window: int) -> float | None:
    average = mean(values, window)
    deviation = standard_deviation(values, window)
    if average is None or deviation is None or deviation == 0.0:
        return None
    return (values[-1] - average) / deviation
