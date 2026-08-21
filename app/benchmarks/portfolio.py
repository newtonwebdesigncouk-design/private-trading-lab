"""Passive asset, equal-universe, and cash baselines for portfolio research."""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

from app.backtesting.analytics import (
    annualised_volatility,
    maximum_drawdown,
    periodic_returns,
    recovery_time,
    sharpe_ratio,
    sortino_ratio,
)
from app.models.market import MarketBar
from app.portfolio.models import (
    PortfolioBenchmarkComparison,
    PortfolioEquityPoint,
    PortfolioMetrics,
)


def _comparison(
    name: str,
    values: Sequence[float],
    portfolio: PortfolioMetrics,
    annual_periods: int,
) -> PortfolioBenchmarkComparison:
    returns = periodic_returns(values)
    total_return = values[-1] / values[0] - 1.0
    years = max((len(values) - 1) / annual_periods, 1.0 / annual_periods)
    annualised_return = (values[-1] / values[0]) ** (1 / years) - 1
    downside = (
        math.sqrt(sum(min(value, 0.0) ** 2 for value in returns) / len(returns))
        * math.sqrt(annual_periods)
        if returns
        else 0.0
    )
    return PortfolioBenchmarkComparison(
        benchmark=name,
        total_return=total_return,
        annualised_return=annualised_return,
        excess_return=portfolio.total_return - total_return,
        tracking_difference=portfolio.annualised_return - annualised_return,
        volatility=annualised_volatility(returns, annual_periods),
        sharpe_ratio=sharpe_ratio(returns, annual_periods),
        sortino_ratio=sortino_ratio(returns, annual_periods),
        maximum_drawdown=maximum_drawdown(values),
        recovery_time_bars=recovery_time(values),
        turnover_difference=portfolio.turnover,
        cost_difference=portfolio.fees_paid + portfolio.slippage_cost,
        downside_risk_difference=portfolio.downside_risk - downside,
    )


def calculate_portfolio_benchmarks(
    bars_by_symbol: Mapping[str, Sequence[MarketBar]],
    timestamps: Sequence[datetime],
    equity_curve: Sequence[PortfolioEquityPoint],
    metrics: PortfolioMetrics,
    *,
    annual_periods: int,
) -> tuple[PortfolioBenchmarkComparison, ...]:
    price_maps = {
        symbol: {bar.timestamp: bar.effective_close for bar in bars}
        for symbol, bars in bars_by_symbol.items()
    }
    starting = equity_curve[0].equity
    comparisons: list[PortfolioBenchmarkComparison] = []
    normalized: dict[str, list[float]] = {}
    for symbol in sorted(price_maps):
        prices = [price_maps[symbol][timestamp] for timestamp in timestamps]
        normalized[symbol] = [starting * price / prices[0] for price in prices]
        comparisons.append(
            _comparison(f"BUY_HOLD_{symbol}", normalized[symbol], metrics, annual_periods)
        )
    equal_weight = [
        sum(normalized[symbol][index] for symbol in normalized) / len(normalized)
        for index in range(len(timestamps))
    ]
    comparisons.append(_comparison("EQUAL_WEIGHT_UNIVERSE", equal_weight, metrics, annual_periods))
    comparisons.append(
        _comparison("CASH_BASELINE", [starting for _ in timestamps], metrics, annual_periods)
    )
    return tuple(comparisons)
