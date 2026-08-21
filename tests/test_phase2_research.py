"""Batch research, hold-out isolation, regimes, and qualification controls."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.backtesting import BacktestConfig, BacktestEngine
from app.models.enums import AssetClass, StrategyState
from app.models.market import Asset, MarketBar
from app.research import (
    Phase2BatchResearchEngine,
    StrategyPortfolioExperiment,
    ValidatedStrategyComponent,
    combine_validated_strategies,
)
from app.strategies.reference import reference_strategies
from app.validation.multiple_testing import (
    approximate_sharpe_p_value,
    benjamini_hochberg,
)
from app.validation.perturbation import evaluate_price_perturbation
from app.validation.qualification import (
    QualificationEvidence,
    QualificationRequirements,
    evaluate_paper_qualification,
)
from app.validation.regimes import analyse_by_regime, classify_regimes


def research_bars(asset: Asset, offset: float = 0.0) -> tuple[MarketBar, ...]:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    closes = [100 + offset + index * 0.08 + 5 * math.sin(index / 3) for index in range(150)]
    return tuple(
        MarketBar(
            timestamp=start + timedelta(days=index),
            open=close * 0.999,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            adjusted_close=close,
            volume=1000 + index * 10,
            asset=asset,
            source="test",
            interval="1d",
        )
        for index, close in enumerate(closes)
    )


def test_batch_research_is_hard_capped_seeded_cross_instrument_and_holdout_locked() -> None:
    first = Asset(symbol="AAA", asset_class=AssetClass.EQUITY, exchange="TEST")
    second = Asset(symbol="BBB", asset_class=AssetClass.EQUITY, exchange="TEST")
    parent = reference_strategies(first.symbol)[0].spec.model_copy(
        update={
            "permitted_assets": (first.symbol, second.symbol),
            "parameters": {
                "strategy_type": "moving_average_crossover",
                "fast_window": 3,
                "slow_window": 8,
            },
        }
    )
    batch_engine = Phase2BatchResearchEngine(maximum_candidates=4)
    kwargs = {
        "dataset_id": "immutable-v1",
        "universe_version": "unit:v1",
        "random_seed": 42,
        "random_search": True,
        "backtest_config": BacktestConfig(position_fraction=0.2),
        "retention_score": 0.0,
        "minimum_validation_trades": 0,
        "false_discovery_rate": 0.99,
    }
    result = batch_engine.run_selection(
        parent,
        {"fast_window": (2, 3, 4), "slow_window": (6, 8, 10)},
        {first.symbol: research_bars(first), second.symbol: research_bars(second, 10)},
        **kwargs,  # type: ignore[arg-type]
    )
    repeated = batch_engine.run_selection(
        parent,
        {"fast_window": (2, 3, 4), "slow_window": (6, 8, 10)},
        {first.symbol: research_bars(first), second.symbol: research_bars(second, 10)},
        **kwargs,  # type: ignore[arg-type]
    )
    assert result.batch_id == repeated.batch_id
    assert result.candidate_space_size == 9
    assert result.candidate_count == 4
    assert result.multiple_testing.candidate_count == 4
    assert result.holdout_locked
    assert set(result.holdout_periods) == {"AAA", "BBB"}
    assert all(
        ":test" not in backtest.dataset_id
        for evaluation in result.evaluations
        for backtest in evaluation.validation_results.values()
    )
    assert all(set(item.validation_results) == {"AAA", "BBB"} for item in result.evaluations)
    assert all(item.cost_stress_ratio >= 0 for item in result.evaluations)
    holdout = batch_engine.evaluate_selected_holdout(
        result,
        {first.symbol: research_bars(first), second.symbol: research_bars(second, 10)},
        backtest_config=BacktestConfig(position_fraction=0.2),
    )
    assert {item.candidate_version for item in holdout} == set(result.selected_candidate_versions)
    assert all(
        backtest.dataset_id.endswith("locked-holdout")
        for item in holdout
        for backtest in item.instrument_results.values()
    )
    with pytest.raises(ValueError, match="approved"):
        batch_engine.generate_cartesian_candidates(parent, {"unknown": (1,)}, random_seed=1)


def test_false_discovery_diagnostic_is_monotonic_and_explainable() -> None:
    diagnostic = benjamini_hochberg({"a": 0.001, "b": 0.02, "c": 0.5, "d": 0.04}, alpha=0.05)
    assert diagnostic.candidate_count == 4
    assert "a" in diagnostic.discoveries
    assert all(0 <= value <= 1 for value in diagnostic.adjusted_q_values.values())
    assert approximate_sharpe_p_value(2.0, 252) < approximate_sharpe_p_value(0.0, 252)
    with pytest.raises(ValueError, match="p-values"):
        benjamini_hochberg({"bad": 2.0})
    with pytest.raises(ValueError, match="alpha"):
        benjamini_hochberg({}, alpha=1)


def test_regime_labels_are_prefix_invariant_and_have_specific_analytics() -> None:
    asset = Asset(symbol="AAA", asset_class=AssetClass.EQUITY, exchange="TEST")
    bars = research_bars(asset)
    full = classify_regimes(bars, lookback=20)
    prefix = classify_regimes(bars[:100], lookback=20)
    assert full[: len(prefix)] == prefix
    assert full[0].calculation_version.endswith("point-in-time")
    assert {item.trend for item in full} <= {"BULLISH", "BEARISH", "SIDEWAYS"}
    strategy = reference_strategies(asset.symbol)[0]
    strategy.spec = strategy.spec.model_copy(
        update={
            "parameters": {
                "strategy_type": "moving_average_crossover",
                "fast_window": 3,
                "slow_window": 8,
            }
        }
    )
    result = BacktestEngine().run(strategy, bars, dataset_id="regime-v1")
    performance = analyse_by_regime(result, full)
    assert performance
    assert sum(item.observations for item in performance) <= len(full)
    assert all(item.fees_and_slippage >= 0 for item in performance)
    perturbed = evaluate_price_perturbation(
        strategy,
        bars,
        BacktestEngine(),
        dataset_id="regime-v1",
        random_seed=1729,
    )
    repeated = evaluate_price_perturbation(
        strategy,
        bars,
        BacktestEngine(),
        dataset_id="regime-v1",
        random_seed=1729,
    )
    assert perturbed == repeated
    with pytest.raises(ValueError, match="cannot be negative"):
        evaluate_price_perturbation(
            strategy,
            bars,
            BacktestEngine(),
            dataset_id="regime-v1",
            random_seed=1,
            maximum_price_noise_bps=-1,
        )


def test_conservative_qualification_does_not_lower_thresholds_to_force_a_pass() -> None:
    evidence = QualificationEvidence(
        score=74,
        out_of_sample_bars=200,
        trades=10,
        maximum_drawdown=0.20,
        cost_stress_ratio=0.5,
        parameter_stability=0.4,
        profitable_walk_forward_fraction=0.4,
        benchmark_excess_return=-0.01,
        final_holdout_isolated=False,
        critical_warnings=("isolated-period dependence",),
    )
    decision = evaluate_paper_qualification(evidence)
    assert not decision.qualified
    assert decision.state is StrategyState.VALIDATION
    assert len(decision.reasons) == 10
    passing = evidence.model_copy(
        update={
            "score": 90,
            "out_of_sample_bars": 300,
            "trades": 40,
            "maximum_drawdown": 0.05,
            "cost_stress_ratio": 0.9,
            "parameter_stability": 0.8,
            "profitable_walk_forward_fraction": 0.8,
            "benchmark_excess_return": 0.05,
            "final_holdout_isolated": True,
            "critical_warnings": (),
        }
    )
    assert (
        evaluate_paper_qualification(passing, QualificationRequirements()).state
        is StrategyState.PAPER_ELIGIBLE
    )


def test_portfolio_of_strategies_requires_independently_validated_components() -> None:
    asset = Asset(symbol="AAA", asset_class=AssetClass.EQUITY, exchange="TEST")
    bars = research_bars(asset)
    strategies = reference_strategies(asset.symbol)[:2]
    results = {
        item.spec.version_key: BacktestEngine().run(item, bars, dataset_id=item.spec.version_key)
        for item in strategies
    }
    experiment = StrategyPortfolioExperiment(
        experiment_id="validated-components-v1",
        components=tuple(
            ValidatedStrategyComponent(
                strategy_version=item.spec.version_key,
                lifecycle_state=StrategyState.PAPER_ELIGIBLE,
                weight=0.4,
            )
            for item in strategies
        ),
    )
    combined = combine_validated_strategies(experiment, results)
    assert set(combined.component_return_attribution) == set(results)
    assert combined.maximum_drawdown >= 0
    with pytest.raises(ValidationError, match="independent validation"):
        StrategyPortfolioExperiment(
            experiment_id="invalid",
            components=(
                ValidatedStrategyComponent(
                    strategy_version="created:v1",
                    lifecycle_state=StrategyState.CREATED,
                    weight=0.2,
                ),
            ),
        )
