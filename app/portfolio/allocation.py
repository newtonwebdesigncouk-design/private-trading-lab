"""Small deterministic allocator catalogue with strict position and exposure caps."""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence

from app.portfolio.models import AllocationPlan


def _bounded_weights(
    raw: Mapping[str, float], *, maximum_position_weight: float, maximum_total_weight: float
) -> dict[str, float]:
    if not 0 < maximum_position_weight <= 1 or not 0 < maximum_total_weight <= 1:
        raise ValueError("allocation caps must lie in (0, 1]")
    positive = {symbol: max(float(value), 0.0) for symbol, value in sorted(raw.items())}
    remaining = maximum_total_weight
    result = {symbol: 0.0 for symbol in positive}
    active = {symbol for symbol, value in positive.items() if value > 0}
    while active and remaining > 1e-12:
        total = sum(positive[symbol] for symbol in active)
        if total <= 0:
            break
        capped: set[str] = set()
        for symbol in sorted(active):
            proposed = remaining * positive[symbol] / total
            room = maximum_position_weight - result[symbol]
            if proposed >= room - 1e-12:
                result[symbol] += max(room, 0.0)
                capped.add(symbol)
        if not capped:
            for symbol in sorted(active):
                result[symbol] += remaining * positive[symbol] / total
            remaining = 0.0
            break
        active.difference_update(capped)
        remaining = maximum_total_weight - sum(result.values())
    return {symbol: weight for symbol, weight in result.items() if weight > 1e-12}


class PortfolioAllocator(ABC):
    name: str

    def __init__(
        self, *, maximum_position_weight: float = 0.20, maximum_total_weight: float = 0.90
    ) -> None:
        self.maximum_position_weight = maximum_position_weight
        self.maximum_total_weight = maximum_total_weight

    @abstractmethod
    def raw_weights(
        self,
        symbols: Sequence[str],
        *,
        volatilities: Mapping[str, float],
        scores: Mapping[str, float],
    ) -> Mapping[str, float]: ...

    def allocate(
        self,
        symbols: Sequence[str],
        *,
        volatilities: Mapping[str, float] | None = None,
        scores: Mapping[str, float] | None = None,
    ) -> AllocationPlan:
        unique = tuple(sorted(set(symbols)))
        weights = _bounded_weights(
            self.raw_weights(unique, volatilities=volatilities or {}, scores=scores or {}),
            maximum_position_weight=self.maximum_position_weight,
            maximum_total_weight=self.maximum_total_weight,
        )
        return AllocationPlan(
            method=self.name,
            weights=weights,
            cash_weight=max(0.0, 1.0 - sum(weights.values())),
        )


class EqualWeightAllocator(PortfolioAllocator):
    name = "equal_weight"

    def raw_weights(
        self,
        symbols: Sequence[str],
        *,
        volatilities: Mapping[str, float],
        scores: Mapping[str, float],
    ) -> Mapping[str, float]:
        del volatilities, scores
        return {symbol: 1.0 for symbol in symbols}


class FixedWeightAllocator(PortfolioAllocator):
    name = "fixed_weight"

    def __init__(self, weights: Mapping[str, float], **kwargs: float) -> None:
        super().__init__(**kwargs)
        if any(value < 0 for value in weights.values()):
            raise ValueError("fixed weights cannot be negative")
        self.weights = dict(weights)

    def raw_weights(
        self,
        symbols: Sequence[str],
        *,
        volatilities: Mapping[str, float],
        scores: Mapping[str, float],
    ) -> Mapping[str, float]:
        del volatilities, scores
        return {symbol: self.weights.get(symbol, 0.0) for symbol in symbols}


class VolatilityAwareAllocator(PortfolioAllocator):
    name = "inverse_volatility"

    def raw_weights(
        self,
        symbols: Sequence[str],
        *,
        volatilities: Mapping[str, float],
        scores: Mapping[str, float],
    ) -> Mapping[str, float]:
        del scores
        return {symbol: 1.0 / max(volatilities.get(symbol, 1.0), 1e-6) for symbol in symbols}


class ScoreWeightedAllocator(PortfolioAllocator):
    name = "score_weighted"

    def raw_weights(
        self,
        symbols: Sequence[str],
        *,
        volatilities: Mapping[str, float],
        scores: Mapping[str, float],
    ) -> Mapping[str, float]:
        del volatilities
        return {symbol: max(scores.get(symbol, 0.0), 0.0) for symbol in symbols}
