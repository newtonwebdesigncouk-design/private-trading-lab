"""Explainable false-discovery diagnostics for larger candidate batches."""

import math
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field


class MultipleTestingDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str = "Benjamini-Hochberg false-discovery-rate"
    candidate_count: int
    alpha: float = Field(gt=0, lt=1)
    raw_p_values: dict[str, float]
    adjusted_q_values: dict[str, float]
    discoveries: tuple[str, ...]
    limitation: str = (
        "Approximate Sharpe p-values assume independent, stationary returns; correlated candidate "
        "tests make this a diagnostic rather than proof of an edge."
    )


def approximate_sharpe_p_value(sharpe: float, observations: int) -> float:
    """One-sided normal approximation used only as an explainable screening diagnostic."""
    if observations < 2:
        return 1.0
    test_statistic = sharpe * math.sqrt(observations / 252)
    return min(max(0.5 * math.erfc(test_statistic / math.sqrt(2)), 0.0), 1.0)


def benjamini_hochberg(
    p_values: Mapping[str, float], *, alpha: float = 0.05
) -> MultipleTestingDiagnostic:
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie in (0, 1)")
    if any(not 0 <= value <= 1 for value in p_values.values()):
        raise ValueError("p-values must lie in [0, 1]")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 1.0
    for reverse_index in range(count - 1, -1, -1):
        identifier, value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, value * count / rank)
        adjusted[identifier] = min(running, 1.0)
    adjusted = {identifier: adjusted[identifier] for identifier in sorted(adjusted)}
    return MultipleTestingDiagnostic(
        candidate_count=count,
        alpha=alpha,
        raw_p_values=dict(sorted(p_values.items())),
        adjusted_q_values=adjusted,
        discoveries=tuple(
            identifier for identifier in sorted(adjusted) if adjusted[identifier] <= alpha
        ),
    )
