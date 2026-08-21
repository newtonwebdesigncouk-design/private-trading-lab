"""Anti-overfitting, bounded research and risk-first score tests."""

from datetime import UTC, datetime

import pytest

from app.backtesting import BacktestConfig, BacktestEngine
from app.data.synthetic import SyntheticMarketDataProvider
from app.models.enums import AssetClass
from app.research import BoundedResearchEngine
from app.scoring import score_strategy
from app.strategies.reference import reference_strategies
from app.validation.regimes import classify_regimes
from app.validation.sensitivity import ParameterSensitivityAnalyzer
from app.validation.splits import chronological_split
from app.validation.walk_forward import WalkForwardConfig, WalkForwardValidator


def equity_data() -> tuple[object, tuple[object, ...]]:
    provider = SyntheticMarketDataProvider(seed=99)
    asset = next(
        item for item in provider.supported_assets() if item.asset_class is AssetClass.EQUITY
    )
    bars = provider.historical_data(
        asset,
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2022, 12, 31, 23, 59, tzinfo=UTC),
    )
    return asset, bars


def test_chronological_split_is_disjoint_and_ordered() -> None:
    train, validation, test = chronological_split(tuple(range(100)))
    assert len(train) == 60
    assert len(validation) == 20
    assert max(train) < min(validation) < max(validation) < min(test)
    assert set(train).isdisjoint(validation)
    assert set(validation).isdisjoint(test)


def test_walk_forward_stores_train_validation_test_separately() -> None:
    asset, untyped_bars = equity_data()
    strategy = reference_strategies(asset.symbol)[0]  # type: ignore[union-attr]
    bars = untyped_bars  # type: ignore[assignment]
    validator = WalkForwardValidator(
        BacktestEngine(BacktestConfig(position_fraction=0.2)),
        WalkForwardConfig(train_bars=120, validation_bars=60, test_bars=60, step_bars=120),
    )
    result = validator.validate(strategy, bars, dataset_id="walk")  # type: ignore[arg-type]
    assert len(result.folds) >= 2
    for fold in result.folds:
        assert fold.train.end < fold.validation.start < fold.validation.end < fold.test.start
        assert ":train" in fold.train.dataset_id
        assert ":validation" in fold.validation.dataset_id
        assert ":test" in fold.test.dataset_id


def test_parameter_sensitivity_flags_and_records_neighbours() -> None:
    asset, untyped_bars = equity_data()
    strategy = reference_strategies(asset.symbol)[1]  # type: ignore[union-attr]
    result = ParameterSensitivityAnalyzer(BacktestEngine()).analyse(
        strategy.spec,
        untyped_bars,  # type: ignore[arg-type]
        {"lookback": (35, 45)},
        dataset_id="sensitivity",
    )
    assert len(result.points) == 2
    assert 0 <= result.stability <= 1
    assert {point.value for point in result.points} == {35, 45}


def test_bounded_research_generates_only_structured_approved_variations() -> None:
    parent = reference_strategies()[0].spec
    research = BoundedResearchEngine(maximum_candidates=2)
    candidates = research.generate_candidates(
        parent, {"fast_window": (18, 19, 21), "slow_window": (55,)}
    )
    assert len(candidates) == 2
    for candidate, reason in candidates:
        assert candidate.parent_strategy == parent.version_key
        assert candidate.creation_method == "bounded_parameter_search"
        assert reason.parameter_changes
        assert candidate.strategy_id != parent.strategy_id
    with pytest.raises(ValueError, match="not approved"):
        research.generate_candidates(parent, {"unapproved": (1,)})


def test_regime_labels_cover_trend_and_volatility() -> None:
    _, untyped_bars = equity_data()
    observations = classify_regimes(untyped_bars, lookback=40)  # type: ignore[arg-type]
    assert observations
    assert {item.trend for item in observations} <= {"BULLISH", "BEARISH", "SIDEWAYS"}
    assert {item.volatility for item in observations} == {"HIGH", "LOW"}


def test_lower_drawdown_can_outrank_higher_return() -> None:
    asset, untyped_bars = equity_data()
    strategy = reference_strategies(asset.symbol)[0]  # type: ignore[union-attr]
    base = BacktestEngine().run(strategy, untyped_bars, dataset_id="score")  # type: ignore[arg-type]
    risky_metrics = base.metrics.model_copy(update={"total_return": 0.15, "maximum_drawdown": 0.50})
    safer_metrics = base.metrics.model_copy(update={"total_return": 0.10, "maximum_drawdown": 0.07})
    risky = base.model_copy(
        update={
            "metrics": risky_metrics,
            "benchmark": base.benchmark.model_copy(update={"excess_return": 0.05}),
        }
    )
    safer = base.model_copy(
        update={
            "metrics": safer_metrics,
            "benchmark": base.benchmark.model_copy(update={"excess_return": 0.00}),
        }
    )
    assert score_strategy(safer).score > score_strategy(risky).score


def test_score_cannot_grant_paper_eligibility_without_out_of_sample_evidence() -> None:
    asset, untyped_bars = equity_data()
    strategy = reference_strategies(asset.symbol)[0]  # type: ignore[union-attr]
    result = BacktestEngine().run(strategy, untyped_bars, dataset_id="in-sample")  # type: ignore[arg-type]
    score = score_strategy(result, parameter_stability=1.0)
    assert score.state.value != "PAPER_ELIGIBLE"
    assert "out-of-sample validation has not been supplied" in score.reasons
