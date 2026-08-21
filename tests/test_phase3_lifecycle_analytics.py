"""Qualification, degradation, retirement, benchmark, and regime governance tests."""

from datetime import UTC, datetime, timedelta

from app.forward.analytics import (
    calculate_drift_diagnostic,
    compare_champion_challengers,
)
from app.forward.lifecycle import evaluate_forward_lifecycle
from app.forward.models import (
    ForwardDriftDiagnostic,
    ForwardPerformance,
    ForwardTrial,
    ForwardTrialSnapshot,
)
from app.models.enums import (
    AssetClass,
    DegradationSeverity,
    ForwardTrialState,
)
from app.models.market import Asset, MarketBar
from app.models.strategy import StrategySpec
from app.strategies.base import Strategy
from app.validation.regimes import classify_regimes
from scripts.phase3_common import replay_trial_manifest


class FixtureStrategy(Strategy):
    def desired_exposure(self, available_history: tuple[MarketBar, ...]) -> float:
        return 0.0


def trial(state: ForwardTrialState = ForwardTrialState.OBSERVING) -> ForwardTrial:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    asset = Asset(symbol="AAA", asset_class=AssetClass.EQUITY, exchange="TEST")
    implementation = FixtureStrategy(
        StrategySpec(
            strategy_id="governance-fixture",
            version=1,
            name="Governance fixture",
            description="Frozen thresholds fixture",
            asset_class=asset.asset_class,
            permitted_assets=(asset.symbol,),
            timeframe="1d",
            indicators=(),
            entry_conditions=("none",),
            exit_conditions=("none",),
            parameters={"strategy_type": "momentum", "lookback": 2, "threshold": 1.0},
            created_at=start,
        )
    )
    manifest = replay_trial_manifest(
        portfolio_id="governance-portfolio",
        strategy=implementation,
        asset=asset,
        start=start,
        code_revision="test",
        source_dataset_id="snapshot-v1",
    )
    return ForwardTrial(
        manifest=manifest,
        state=state,
        started_at=start,
        updated_at=start,
        failed_evaluations=2 if state is ForwardTrialState.FAILED_FORWARD else 0,
    )


def performance(trial_id: str, **updates: object) -> ForwardPerformance:
    values: dict[str, object] = {
        "trial_id": trial_id,
        "observations": 100,
        "elapsed_days": 120,
        "total_return": 0.10,
        "annualised_volatility": 0.12,
        "sharpe_ratio": 1.0,
        "sortino_ratio": 1.2,
        "maximum_drawdown": 0.05,
        "benchmark_return": 0.04,
        "excess_return": 0.06,
        "hit_rate": 0.60,
        "expectancy": 10.0,
        "turnover": 0.5,
        "costs": 10.0,
        "cost_resilience": 0.90,
        "signal_frequency": 0.30,
        "trades": 12,
        "regime_mix": {"BULLISH/LOW": 60, "SIDEWAYS/HIGH": 40},
    }
    values.update(updates)
    return ForwardPerformance.model_validate(values)


def diagnostic(
    trial_id: str, severity: DegradationSeverity = DegradationSeverity.HEALTHY
) -> ForwardDriftDiagnostic:
    return ForwardDriftDiagnostic(
        trial_id=trial_id,
        timestamp=datetime(2024, 5, 1, tzinfo=UTC),
        window=20,
        rolling_return=0.02,
        rolling_volatility=0.10,
        rolling_sharpe=0.8,
        rolling_sortino=1.0,
        rolling_drawdown=0.03,
        benchmark_relative_return=0.01,
        hit_rate=0.55,
        expectancy=1.0,
        turnover_per_observation=0.01,
        cost_ratio=0.02,
        signal_frequency=0.30,
        volatility_ratio=0.8,
        signal_frequency_ratio=0.8,
        regime_mix={"BULLISH/LOW": 20},
        data_age_seconds=0,
        severity=severity,
        reasons=("frozen diagnostic",),
    )


def test_minimum_evidence_qualification_pause_failure_and_retirement_are_explainable() -> None:
    observing = trial()
    qualified = evaluate_forward_lifecycle(
        observing,
        performance(observing.manifest.trial_id),
        diagnostic(observing.manifest.trial_id),
        cycle_id="cycle-qualified",
        timestamp=datetime(2024, 5, 1, tzinfo=UTC),
    )
    assert qualified.new_state is ForwardTrialState.QUALIFIED_FORWARD
    assert qualified.rule_id == "QUALIFIED_FORWARD_PAPER_ONLY"
    assert "paper observation only" in str(qualified.evidence["qualified_forward_meaning"])

    pending = evaluate_forward_lifecycle(
        observing,
        performance(observing.manifest.trial_id, observations=10, elapsed_days=10, trades=0),
        diagnostic(observing.manifest.trial_id),
        cycle_id="cycle-pending",
        timestamp=datetime(2024, 1, 11, tzinfo=UTC),
    )
    assert pending.new_state is ForwardTrialState.OBSERVING
    assert pending.rule_id == "MINIMUM_EVIDENCE_PENDING"
    assert len(pending.reasons) >= 3

    data_pause = evaluate_forward_lifecycle(
        observing,
        performance(observing.manifest.trial_id),
        diagnostic(observing.manifest.trial_id),
        cycle_id="cycle-data",
        timestamp=datetime(2024, 5, 1, tzinfo=UTC),
        unresolved_data_quality_failures=1,
    )
    assert data_pause.new_state is ForwardTrialState.PAUSED_DATA_QUALITY
    risk_pause = evaluate_forward_lifecycle(
        observing,
        performance(observing.manifest.trial_id),
        diagnostic(observing.manifest.trial_id, DegradationSeverity.PAUSE),
        cycle_id="cycle-risk",
        timestamp=datetime(2024, 5, 1, tzinfo=UTC),
    )
    assert risk_pause.new_state is ForwardTrialState.PAUSED_RISK
    failed = evaluate_forward_lifecycle(
        observing,
        performance(observing.manifest.trial_id),
        diagnostic(observing.manifest.trial_id, DegradationSeverity.FAIL),
        cycle_id="cycle-fail",
        timestamp=datetime(2024, 5, 1, tzinfo=UTC),
    )
    assert failed.new_state is ForwardTrialState.FAILED_FORWARD
    failing = trial(ForwardTrialState.FAILED_FORWARD)
    retired = evaluate_forward_lifecycle(
        failing,
        performance(failing.manifest.trial_id),
        diagnostic(failing.manifest.trial_id),
        cycle_id="cycle-retire",
        timestamp=datetime(2024, 5, 2, tzinfo=UTC),
    )
    assert retired.new_state is ForwardTrialState.RETIRED
    assert retired.rule_id == "AUTOMATIC_RETIREMENT"


def test_rolling_drift_champion_comparison_and_regimes_use_only_available_prefix() -> None:
    forward_trial = trial()
    start = forward_trial.manifest.start_timestamp
    snapshots = tuple(
        ForwardTrialSnapshot(
            trial_id=forward_trial.manifest.trial_id,
            timestamp=start + timedelta(days=index),
            cash=0,
            market_value=value,
            equity=value,
            realised_pnl=0,
            unrealised_pnl=value - 54_000,
            drawdown=max(0.0, 1 - value / 54_000),
            allocation=0.18,
        )
        for index, value in enumerate(
            (54_000, 53_000, 51_000, 49_000, 47_000, 45_000, 43_000, 41_000, 39_000)
        )
    )
    drift = calculate_drift_diagnostic(
        forward_trial.manifest,
        performance(
            forward_trial.manifest.trial_id,
            observations=100,
            excess_return=-0.20,
            maximum_drawdown=0.28,
        ),
        snapshots,
        data_age_seconds=0,
    )
    assert drift.severity in {DegradationSeverity.PAUSE, DegradationSeverity.FAIL}
    assert drift.reasons

    challenger_id = "forward-challenger"
    comparison = compare_champion_challengers(
        {
            forward_trial.manifest.trial_id: performance(forward_trial.manifest.trial_id),
            challenger_id: performance(challenger_id, excess_return=0.01, sharpe_ratio=0.6),
        },
        {
            forward_trial.manifest.trial_id: ForwardTrialState.QUALIFIED_FORWARD,
            challenger_id: ForwardTrialState.OBSERVING,
        },
        {
            forward_trial.manifest.trial_id: (0.01, 0.02, -0.01),
            challenger_id: (0.00, 0.01, -0.01),
        },
        {
            forward_trial.manifest.trial_id: {"AAA": 0.18},
            challenger_id: {"AAA": 0.10},
        },
    )
    assert comparison.champion_trial_id == forward_trial.manifest.trial_id
    assert (
        comparison.overlapping_exposure[f"{forward_trial.manifest.trial_id}|{challenger_id}"]
        == 0.10
    )
    assert "never authorises live" in comparison.qualification_note

    asset = forward_trial.manifest.assets[0]
    history = tuple(
        MarketBar(
            timestamp=start + timedelta(days=index),
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            adjusted_close=100 + index,
            volume=1_000 + index,
            asset=asset,
            source="regime-fixture",
            interval="1d",
        )
        for index in range(50)
    )
    prefix_labels = classify_regimes(history[:45], lookback=10)
    full_labels = classify_regimes(history, lookback=10)
    assert prefix_labels == full_labels[: len(prefix_labels)]
