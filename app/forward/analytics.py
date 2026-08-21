"""Deterministic forward performance, degradation, and champion/challenger analytics."""

import math
from collections import Counter
from collections.abc import Mapping, Sequence

import numpy as np

from app.backtesting.analytics import (
    annualised_volatility,
    maximum_drawdown,
    periodic_returns,
    sharpe_ratio,
    sortino_ratio,
)
from app.forward.models import (
    ChampionChallengerComparison,
    ForwardDriftDiagnostic,
    ForwardFill,
    ForwardObservation,
    ForwardPerformance,
    ForwardSignal,
    ForwardTrialManifest,
    ForwardTrialSnapshot,
)
from app.models.enums import DegradationSeverity, ForwardTrialState


def _benchmark_return(
    manifest: ForwardTrialManifest, observations: Sequence[ForwardObservation]
) -> float:
    if manifest.benchmark.method == "CASH":
        return 0.0
    returns: list[float] = []
    for symbol in manifest.benchmark.symbols:
        prices = [
            item.bar.effective_close for item in observations if item.bar.asset.symbol == symbol
        ]
        if len(prices) > 1:
            returns.append(prices[-1] / prices[0] - 1.0)
    if not returns:
        return 0.0
    return sum(returns) / len(returns)


def calculate_forward_performance(
    manifest: ForwardTrialManifest,
    snapshots: Sequence[ForwardTrialSnapshot],
    observations: Sequence[ForwardObservation],
    signals: Sequence[ForwardSignal],
    fills: Sequence[ForwardFill],
    *,
    trade_pnl: Sequence[float],
    annual_periods: int = 252,
) -> ForwardPerformance:
    relevant_snapshots = [item for item in snapshots if item.trial_id == manifest.trial_id]
    relevant_observations = [item for item in observations if item.trial_id == manifest.trial_id]
    relevant_signals = [item for item in signals if item.trial_id == manifest.trial_id]
    relevant_fills = [item for item in fills if item.trial_id == manifest.trial_id]
    values = [item.equity for item in relevant_snapshots]
    returns = periodic_returns(values)
    starting = manifest.allocated_capital
    ending = values[-1] if values else starting
    total_return = ending / starting - 1.0
    costs = sum(item.fill.fee + item.fill.slippage_cost for item in relevant_fills)
    gross_movement = abs(ending - starting) + costs
    cost_resilience = 1.0 if costs == 0 else max(0.0, 1.0 - costs / gross_movement)
    winners = [value for value in trade_pnl if value > 0]
    elapsed_days = (
        max(0, (relevant_snapshots[-1].timestamp - manifest.start_timestamp).days)
        if relevant_snapshots
        else 0
    )
    benchmark_return = _benchmark_return(manifest, relevant_observations)
    return ForwardPerformance(
        trial_id=manifest.trial_id,
        observations=len(relevant_observations),
        elapsed_days=elapsed_days,
        total_return=total_return,
        annualised_volatility=annualised_volatility(returns, annual_periods),
        sharpe_ratio=sharpe_ratio(returns, annual_periods),
        sortino_ratio=sortino_ratio(returns, annual_periods),
        maximum_drawdown=maximum_drawdown(values),
        benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return,
        hit_rate=len(winners) / len(trade_pnl) if trade_pnl else 0.0,
        expectancy=sum(trade_pnl) / len(trade_pnl) if trade_pnl else 0.0,
        turnover=(
            sum(item.fill.notional for item in relevant_fills) / starting if starting else 0.0
        ),
        costs=costs,
        cost_resilience=cost_resilience,
        signal_frequency=(
            sum(item.desired_exposure > 0 for item in relevant_signals) / len(relevant_observations)
            if relevant_observations
            else 0.0
        ),
        trades=len(trade_pnl),
        regime_mix=dict(
            sorted(Counter(item.regime or "UNCLASSIFIED" for item in relevant_observations).items())
        ),
    )


def calculate_drift_diagnostic(
    manifest: ForwardTrialManifest,
    performance: ForwardPerformance,
    snapshots: Sequence[ForwardTrialSnapshot],
    *,
    data_age_seconds: float,
    annual_periods: int = 252,
) -> ForwardDriftDiagnostic:
    policy = manifest.degradation_policy
    values = [item.equity for item in snapshots if item.trial_id == manifest.trial_id]
    window_values = values[-(policy.rolling_window + 1) :]
    returns = periodic_returns(window_values)
    rolling_return = window_values[-1] / window_values[0] - 1.0 if len(window_values) > 1 else 0.0
    volatility = annualised_volatility(returns, annual_periods)
    baseline_volatility = manifest.baseline_profile.annualised_volatility
    volatility_ratio = (
        volatility / baseline_volatility
        if baseline_volatility > 0
        else (1.0 if volatility == 0 else math.inf)
    )
    baseline_frequency = manifest.baseline_profile.signal_frequency
    frequency_ratio = (
        performance.signal_frequency / baseline_frequency
        if baseline_frequency > 0
        else (1.0 if performance.signal_frequency == 0 else math.inf)
    )
    reasons: list[str] = []
    severity = DegradationSeverity.HEALTHY
    if performance.observations < policy.minimum_observations:
        reasons.append("insufficient observations for degradation decision")
    else:
        rolling_sharpe = sharpe_ratio(returns, annual_periods)
        rolling_drawdown = maximum_drawdown(window_values)
        if rolling_drawdown >= policy.fail_drawdown:
            severity = DegradationSeverity.FAIL
            reasons.append("rolling drawdown reached the frozen fail threshold")
        elif (
            rolling_drawdown >= policy.pause_drawdown
            or rolling_sharpe <= policy.pause_sharpe
            or performance.excess_return <= policy.pause_excess_return
            or volatility_ratio >= policy.maximum_volatility_ratio
            or frequency_ratio >= policy.maximum_signal_frequency_ratio
        ):
            severity = DegradationSeverity.PAUSE
            reasons.append("one or more frozen degradation pause thresholds were breached")
        elif (
            rolling_sharpe <= policy.warning_sharpe
            or performance.excess_return <= policy.warning_excess_return
        ):
            severity = DegradationSeverity.WARNING
            reasons.append("forward performance breached a frozen warning threshold")
    if not reasons:
        reasons.append("rolling diagnostics remain within frozen limits")
    return ForwardDriftDiagnostic(
        trial_id=manifest.trial_id,
        timestamp=snapshots[-1].timestamp if snapshots else manifest.start_timestamp,
        window=policy.rolling_window,
        rolling_return=rolling_return,
        rolling_volatility=volatility,
        rolling_sharpe=sharpe_ratio(returns, annual_periods),
        rolling_sortino=sortino_ratio(returns, annual_periods),
        rolling_drawdown=maximum_drawdown(window_values),
        benchmark_relative_return=performance.excess_return,
        hit_rate=performance.hit_rate,
        expectancy=performance.expectancy,
        turnover_per_observation=(
            performance.turnover / performance.observations if performance.observations else 0.0
        ),
        cost_ratio=(
            performance.costs
            / (abs(performance.total_return * manifest.allocated_capital) + performance.costs)
            if performance.costs
            else 0.0
        ),
        signal_frequency=performance.signal_frequency,
        volatility_ratio=volatility_ratio,
        signal_frequency_ratio=frequency_ratio,
        regime_mix=performance.regime_mix,
        data_age_seconds=max(data_age_seconds, 0.0),
        severity=severity,
        reasons=tuple(reasons),
    )


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    length = min(len(left), len(right))
    if length < 2:
        return 0.0
    left_values = np.asarray(left[-length:], dtype=float)
    right_values = np.asarray(right[-length:], dtype=float)
    if float(np.std(left_values)) == 0 or float(np.std(right_values)) == 0:
        return 0.0
    return float(np.corrcoef(left_values, right_values)[0, 1])


def compare_champion_challengers(
    performance: Mapping[str, ForwardPerformance],
    states: Mapping[str, ForwardTrialState],
    return_series: Mapping[str, Sequence[float]],
    position_weights: Mapping[str, Mapping[str, float]],
) -> ChampionChallengerComparison:
    state_priority = {
        ForwardTrialState.QUALIFIED_FORWARD: 0,
        ForwardTrialState.OBSERVING: 1,
        ForwardTrialState.READY_FOR_FORWARD: 2,
        ForwardTrialState.PAUSED_DATA_QUALITY: 3,
        ForwardTrialState.PAUSED_RISK: 4,
        ForwardTrialState.FAILED_FORWARD: 5,
        ForwardTrialState.RETIRED: 6,
    }
    ranking = tuple(
        sorted(
            performance,
            key=lambda trial_id: (
                state_priority[states[trial_id]],
                -performance[trial_id].excess_return,
                -performance[trial_id].sharpe_ratio,
                trial_id,
            ),
        )
    )
    pairwise: dict[str, dict[str, float]] = {}
    overlap: dict[str, float] = {}
    for left in sorted(performance):
        pairwise[left] = {}
        for right in sorted(performance):
            pairwise[left][right] = (
                1.0
                if left == right
                else _correlation(return_series.get(left, ()), return_series.get(right, ()))
            )
            if left < right:
                overlap[f"{left}|{right}"] = sum(
                    min(weight, position_weights.get(right, {}).get(symbol, 0.0))
                    for symbol, weight in position_weights.get(left, {}).items()
                )
    drawdown_weighted = {
        trial_id: performance[trial_id].maximum_drawdown
        * sum(position_weights.get(trial_id, {}).values())
        for trial_id in performance
    }
    total = sum(drawdown_weighted.values())
    drawdown_contribution = {
        trial_id: value / total if total else 0.0
        for trial_id, value in sorted(drawdown_weighted.items())
    }
    return ChampionChallengerComparison(
        champion_trial_id=ranking[0] if ranking else None,
        ranking=ranking,
        performance=dict(performance),
        pairwise_return_correlation=pairwise,
        overlapping_exposure=overlap,
        drawdown_contribution=drawdown_contribution,
    )
