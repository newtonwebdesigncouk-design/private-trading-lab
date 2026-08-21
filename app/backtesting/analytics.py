"""Performance analytics with explicit, defensive edge-case handling."""

import math
from collections.abc import Sequence

import numpy as np

from app.backtesting.models import EquityPoint, PerformanceMetrics, SimulatedFill, Trade


def periodic_returns(values: Sequence[float]) -> list[float]:
    return [values[index] / values[index - 1] - 1.0 for index in range(1, len(values))]


def annualised_volatility(returns: Sequence[float], annual_periods: int) -> float:
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns, ddof=1) * math.sqrt(annual_periods))


def sharpe_ratio(returns: Sequence[float], annual_periods: int) -> float:
    if len(returns) < 2:
        return 0.0
    deviation = float(np.std(returns, ddof=1))
    return (
        0.0 if deviation == 0 else float(np.mean(returns) / deviation * math.sqrt(annual_periods))
    )


def sortino_ratio(returns: Sequence[float], annual_periods: int) -> float:
    if not returns:
        return 0.0
    downside = [minimum for value in returns if (minimum := min(value, 0.0)) < 0]
    if not downside:
        return 0.0
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(returns))
    return (
        0.0
        if downside_deviation == 0
        else float(np.mean(returns) / downside_deviation * math.sqrt(annual_periods))
    )


def maximum_drawdown(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return abs(worst)


def recovery_time(values: Sequence[float]) -> int | None:
    """Longest completed peak-to-recovery duration, or None if the final drawdown is open."""
    if not values:
        return 0
    peak = values[0]
    peak_index = 0
    longest = 0
    in_drawdown = False
    for index, value in enumerate(values):
        if value >= peak:
            if in_drawdown:
                longest = max(longest, index - peak_index)
            peak = value
            peak_index = index
            in_drawdown = False
        else:
            in_drawdown = True
    return None if in_drawdown else longest


def calculate_metrics(
    equity_curve: Sequence[EquityPoint],
    trades: Sequence[Trade],
    fills: Sequence[SimulatedFill],
    annual_periods: int,
) -> PerformanceMetrics:
    if not equity_curve:
        raise ValueError("an equity curve is required")
    values = [point.equity for point in equity_curve]
    returns = periodic_returns(values)
    start, end = values[0], values[-1]
    total_return = end / start - 1.0
    years = max((len(values) - 1) / annual_periods, 1.0 / annual_periods)
    annualised_return = (end / start) ** (1.0 / years) - 1.0
    winners = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losers = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    trade_count = len(trades)
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else 0.0)
    average_equity = sum(values) / len(values)
    turnover = sum(fill.notional for fill in fills) / average_equity if average_equity else 0.0
    exposure = sum(point.position_quantity > 0 for point in equity_curve) / len(equity_curve)
    return PerformanceMetrics(
        total_return=total_return,
        annualised_return=annualised_return,
        volatility=annualised_volatility(returns, annual_periods),
        sharpe_ratio=sharpe_ratio(returns, annual_periods),
        sortino_ratio=sortino_ratio(returns, annual_periods),
        maximum_drawdown=maximum_drawdown(values),
        recovery_time_bars=recovery_time(values),
        win_rate=len(winners) / trade_count if trade_count else 0.0,
        loss_rate=len(losers) / trade_count if trade_count else 0.0,
        average_winner=sum(winners) / len(winners) if winners else 0.0,
        average_loser=sum(losers) / len(losers) if losers else 0.0,
        profit_factor=profit_factor,
        expectancy=sum(trade.net_pnl for trade in trades) / trade_count if trade_count else 0.0,
        number_of_trades=trade_count,
        turnover=turnover,
        exposure=exposure,
        fees_paid=sum(fill.fee for fill in fills),
        slippage_cost=sum(fill.slippage_cost for fill in fills),
    )
