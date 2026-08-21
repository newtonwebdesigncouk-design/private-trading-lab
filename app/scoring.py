"""Risk-first strategy scoring; high raw return alone is insufficient."""

import math

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting.models import BacktestResult
from app.models.enums import StrategyState


class StrategyScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0, le=100)
    state: StrategyState
    components: dict[str, float]
    reasons: tuple[str, ...]


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def score_strategy(
    result: BacktestResult,
    *,
    parameter_stability: float = 0.5,
    out_of_sample_validated: bool = False,
) -> StrategyScore:
    metrics = result.metrics
    finite_profit_factor = (
        min(metrics.profit_factor, 3.0) if math.isfinite(metrics.profit_factor) else 3.0
    )
    components = {
        "capital_preservation": 20 * _clamp(1 - metrics.maximum_drawdown / 0.30),
        "sharpe": 15 * _clamp((metrics.sharpe_ratio + 0.5) / 2.5),
        "sortino": 10 * _clamp((metrics.sortino_ratio + 0.5) / 3.0),
        "out_of_sample_return": (
            12 * _clamp((metrics.total_return + 0.10) / 0.40) if out_of_sample_validated else 0.0
        ),
        "benchmark_advantage": 10 * _clamp((result.benchmark.excess_return + 0.10) / 0.25),
        "consistency": 8 * _clamp((finite_profit_factor - 0.5) / 1.5),
        "parameter_stability": 10 * _clamp(parameter_stability),
        "trade_sample": 7 * _clamp(metrics.number_of_trades / 25),
        "cost_resilience": 5
        * _clamp(
            1
            - (metrics.fees_paid + metrics.slippage_cost) / max(result.starting_capital * 0.03, 1.0)
        ),
        "volatility_control": 3 * _clamp(1 - metrics.volatility / 0.40),
    }
    score = round(sum(components.values()), 2)
    reasons: list[str] = []
    if metrics.maximum_drawdown > 0.20:
        reasons.append("drawdown exceeds the 20% research tolerance")
    if metrics.number_of_trades < 8:
        reasons.append("trade sample is too small for qualification")
    if result.benchmark.excess_return < 0:
        reasons.append("underperformed the passive benchmark")
    if metrics.sharpe_ratio < 0.5:
        reasons.append("risk-adjusted return is weak")
    if parameter_stability < 0.5:
        reasons.append("nearby parameters are fragile")
    if not out_of_sample_validated:
        reasons.append("out-of-sample validation has not been supplied")
    if score < 40 or metrics.maximum_drawdown > 0.30:
        state = StrategyState.REJECTED
        reasons.append("risk-first score did not clear the rejection threshold")
    elif not out_of_sample_validated or score < 70 or metrics.number_of_trades < 8:
        state = StrategyState.VALIDATION
        reasons.append("requires further out-of-sample validation")
    else:
        state = StrategyState.PAPER_ELIGIBLE
        reasons.append("eligible for paper simulation only")
    return StrategyScore(score=score, state=state, components=components, reasons=tuple(reasons))
