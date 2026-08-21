"""Compare a strategy against a transparent passive buy-and-hold benchmark."""

from collections.abc import Sequence

from app.backtesting.analytics import (
    annualised_volatility,
    maximum_drawdown,
    periodic_returns,
    sharpe_ratio,
)
from app.backtesting.models import BenchmarkComparison, PerformanceMetrics
from app.models.market import MarketBar


def compare_with_buy_and_hold(
    metrics: PerformanceMetrics, bars: Sequence[MarketBar], annual_periods: int
) -> BenchmarkComparison:
    if len(bars) < 2:
        raise ValueError("at least two bars are required for a benchmark")
    prices = [bar.effective_close for bar in bars]
    benchmark_return = prices[-1] / prices[0] - 1.0
    benchmark_returns = periodic_returns(prices)
    benchmark_volatility = annualised_volatility(benchmark_returns, annual_periods)
    benchmark_sharpe = sharpe_ratio(benchmark_returns, annual_periods)
    benchmark_drawdown = maximum_drawdown(prices)
    return BenchmarkComparison(
        benchmark_symbol=f"BUY_HOLD_{bars[0].asset.symbol}",
        strategy_return=metrics.total_return,
        benchmark_return=benchmark_return,
        excess_return=metrics.total_return - benchmark_return,
        strategy_drawdown=metrics.maximum_drawdown,
        benchmark_drawdown=benchmark_drawdown,
        relative_drawdown=benchmark_drawdown - metrics.maximum_drawdown,
        strategy_volatility=metrics.volatility,
        benchmark_volatility=benchmark_volatility,
        volatility_difference=metrics.volatility - benchmark_volatility,
        strategy_sharpe=metrics.sharpe_ratio,
        benchmark_sharpe=benchmark_sharpe,
        risk_adjusted_advantage=metrics.sharpe_ratio - benchmark_sharpe,
    )
