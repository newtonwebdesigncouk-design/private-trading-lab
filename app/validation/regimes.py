"""Deterministic point-in-time regime labels and regime-specific analytics."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.backtesting.analytics import (
    annualised_volatility,
    maximum_drawdown,
    periodic_returns,
    sharpe_ratio,
    sortino_ratio,
)
from app.backtesting.models import BacktestResult
from app.models.market import MarketBar

REGIME_CALCULATION_VERSION = "trend-volatility-liquidity-v2-point-in-time"


class RegimeObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    trend: str
    volatility: str
    liquidity: str | None = None
    calculation_version: str = REGIME_CALCULATION_VERSION
    lookback: int

    @property
    def label(self) -> str:
        parts = [self.trend, self.volatility]
        if self.liquidity is not None:
            parts.append(self.liquidity)
        return "/".join(parts)


class RegimePerformance(BaseModel):
    model_config = ConfigDict(frozen=True)

    regime: str
    observations: int
    total_return: float
    maximum_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    trade_count: int
    win_rate: float
    loss_rate: float
    fees_and_slippage: float
    cost_sensitivity: float


def classify_regimes(
    bars: Sequence[MarketBar], *, lookback: int = 40, annual_periods: int = 252
) -> tuple[RegimeObservation, ...]:
    """Each label uses only the prefix ending at its own timestamp."""
    if lookback < 2:
        raise ValueError("lookback must be at least two")
    observations: list[RegimeObservation] = []
    closes = [bar.effective_close for bar in bars]
    volumes = [bar.volume for bar in bars]
    for index in range(lookback, len(bars)):
        window = closes[index - lookback : index + 1]
        trailing_return = window[-1] / window[0] - 1.0
        if trailing_return > 0.05:
            trend = "BULLISH"
        elif trailing_return < -0.05:
            trend = "BEARISH"
        else:
            trend = "SIDEWAYS"
        current_volatility = annualised_volatility(periodic_returns(window), annual_periods)
        baseline_start = max(0, index - lookback * 3)
        baseline_window = closes[baseline_start : index + 1]
        baseline_volatility = annualised_volatility(
            periodic_returns(baseline_window), annual_periods
        )
        volatility = "HIGH" if current_volatility > baseline_volatility else "LOW"
        volume_window = volumes[index - lookback : index + 1]
        positive_volume = [value for value in volume_window if value > 0]
        liquidity: str | None = None
        if positive_volume:
            recent_count = min(5, len(positive_volume))
            recent = sum(positive_volume[-recent_count:]) / recent_count
            baseline = sum(positive_volume) / len(positive_volume)
            liquidity = "HIGH_LIQUIDITY" if recent >= baseline else "LOW_LIQUIDITY"
        observations.append(
            RegimeObservation(
                timestamp=bars[index].timestamp,
                trend=trend,
                volatility=volatility,
                liquidity=liquidity,
                lookback=lookback,
            )
        )
    return tuple(observations)


def analyse_by_regime(
    result: BacktestResult,
    observations: Sequence[RegimeObservation],
    *,
    annual_periods: int = 252,
) -> tuple[RegimePerformance, ...]:
    labels = {observation.timestamp: observation.label for observation in observations}
    curves: dict[str, list[float]] = defaultdict(list)
    for point in result.equity_curve:
        label = labels.get(point.timestamp)
        if label is not None:
            curves[label].append(point.equity)
    trades: dict[str, list[float]] = defaultdict(list)
    for trade in result.trades:
        label = labels.get(trade.exit_timestamp)
        if label is not None:
            trades[label].append(trade.net_pnl)
    costs: dict[str, float] = defaultdict(float)
    for fill in result.fills:
        label = labels.get(fill.timestamp)
        if label is not None:
            costs[label] += fill.fee + fill.slippage_cost

    performance: list[RegimePerformance] = []
    for label, values in sorted(curves.items()):
        returns = periodic_returns(values)
        pnl = trades[label]
        gross_movement = abs(values[-1] - values[0]) if len(values) > 1 else 0.0
        performance.append(
            RegimePerformance(
                regime=label,
                observations=len(values),
                total_return=values[-1] / values[0] - 1 if len(values) > 1 else 0.0,
                maximum_drawdown=maximum_drawdown(values),
                sharpe_ratio=sharpe_ratio(returns, annual_periods),
                sortino_ratio=sortino_ratio(returns, annual_periods),
                trade_count=len(pnl),
                win_rate=sum(value > 0 for value in pnl) / len(pnl) if pnl else 0.0,
                loss_rate=sum(value < 0 for value in pnl) / len(pnl) if pnl else 0.0,
                fees_and_slippage=costs[label],
                cost_sensitivity=costs[label] / gross_movement if gross_movement else 0.0,
            )
        )
    return tuple(performance)
