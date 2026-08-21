"""Shared constructors for explicit Phase 3 owner commands and replay verification."""

import subprocess
from datetime import UTC, datetime

from app.backtesting.models import CostAssumptions
from app.forward.models import (
    ForwardBaselineProfile,
    ForwardBenchmarkDefinition,
    ForwardDataPolicy,
    ForwardDegradationPolicy,
    ForwardQualificationPolicy,
    ForwardRiskPolicy,
    ForwardTrialManifest,
)
from app.models.enums import ObservationProvenance
from app.models.market import Asset
from app.risk import RiskLimits
from app.strategies.base import Strategy


def revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, check=False, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def replay_trial_manifest(
    *,
    portfolio_id: str,
    strategy: Strategy,
    asset: Asset,
    start: datetime,
    code_revision: str,
    source_dataset_id: str,
    allocation_weight: float = 0.18,
) -> ForwardTrialManifest:
    """Create a deterministic frozen engineering trial before any replay is revealed."""
    fixed_spec = strategy.spec.model_copy(update={"created_at": start})
    return ForwardTrialManifest.create(
        portfolio_id=portfolio_id,
        strategy=fixed_spec,
        assets=(asset,),
        universe_version=f"{source_dataset_id}:phase3-replay-universe-v1",
        benchmark=ForwardBenchmarkDefinition(
            benchmark_id=f"{asset.symbol}-buy-and-hold-v1",
            symbols=(asset.symbol,),
        ),
        portfolio_starting_capital=300_000.0,
        allocation_weight=allocation_weight,
        costs=CostAssumptions(),
        risk_policy=ForwardRiskPolicy(
            version="phase3-paper-risk-v1",
            limits=RiskLimits(stale_after=RiskLimits().stale_after),
            maximum_strategy_allocation=0.25,
        ),
        data_policy=ForwardDataPolicy(
            provider_name="immutable-historical-replay",
            provider_version="phase3-replay-v1",
            interval="1d",
            adjustment_policy="TOTAL_RETURN_ADJUSTED",
            corporate_action_policy="frozen Phase 2 snapshot policy",
            warmup_dataset_id=source_dataset_id,
            version="phase3-replay-data-v1",
        ),
        start_timestamp=start,
        qualification_policy=ForwardQualificationPolicy(
            version="phase3-qualification-v1",
            minimum_elapsed_days=90,
            minimum_observations=60,
            minimum_trades=5,
            maximum_drawdown=0.15,
            minimum_sharpe=0.50,
            minimum_excess_return=0.0,
            minimum_cost_resilience=0.70,
        ),
        degradation_policy=ForwardDegradationPolicy(
            version="phase3-degradation-v1",
            rolling_window=20,
            minimum_observations=20,
            retire_after_failed_evaluations=3,
        ),
        baseline_profile=ForwardBaselineProfile(
            annualised_volatility=0.20,
            signal_frequency=0.40,
            turnover_per_observation=0.02,
            hit_rate=0.50,
            expectancy=0.0,
            source_experiment_id=f"{source_dataset_id}:{fixed_spec.version_key}",
        ),
        code_revision=code_revision,
        provenance=ObservationProvenance.REPLAY,
        random_seed=1729,
        created_at=start.astimezone(UTC),
    )
