"""Deterministic labels for initial cross-regime result slicing."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.backtesting.analytics import annualised_volatility, periodic_returns
from app.models.market import MarketBar


class RegimeObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: object
    trend: str
    volatility: str


def classify_regimes(
    bars: Sequence[MarketBar], *, lookback: int = 40, annual_periods: int = 252
) -> tuple[RegimeObservation, ...]:
    if lookback < 2:
        raise ValueError("lookback must be at least two")
    observations: list[RegimeObservation] = []
    closes = [bar.effective_close for bar in bars]
    all_returns = periodic_returns(closes)
    baseline_volatility = annualised_volatility(all_returns, annual_periods)
    for index in range(lookback, len(bars)):
        window = closes[index - lookback : index + 1]
        trailing_return = window[-1] / window[0] - 1.0
        if trailing_return > 0.05:
            trend = "BULLISH"
        elif trailing_return < -0.05:
            trend = "BEARISH"
        else:
            trend = "SIDEWAYS"
        volatility = annualised_volatility(periodic_returns(window), annual_periods)
        observations.append(
            RegimeObservation(
                timestamp=bars[index].timestamp,
                trend=trend,
                volatility="HIGH" if volatility > baseline_volatility else "LOW",
            )
        )
    return tuple(observations)
