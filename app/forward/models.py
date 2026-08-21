"""Immutable Phase 3 trial manifests and forward-observation records."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.models import CostAssumptions, SimulatedFill, SimulatedOrder, Trade
from app.models.enums import (
    DegradationSeverity,
    ForwardCycleStatus,
    ForwardTrialState,
    ObservationProvenance,
)
from app.models.market import Asset, MarketBar
from app.models.strategy import StrategySpec
from app.risk import RiskLimits


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def strategy_fingerprint(strategy: StrategySpec) -> str:
    return canonical_hash(strategy.model_dump(mode="json"))


class ForwardBenchmarkDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    benchmark_id: str
    method: str = "BUY_AND_HOLD"
    symbols: tuple[str, ...]
    version: str = "v1"

    @model_validator(mode="after")
    def require_supported_benchmark(self) -> "ForwardBenchmarkDefinition":
        if self.method not in {"BUY_AND_HOLD", "EQUAL_WEIGHT", "CASH"}:
            raise ValueError("unsupported frozen forward benchmark method")
        if self.method != "CASH" and not self.symbols:
            raise ValueError("non-cash benchmark requires at least one symbol")
        return self


class ForwardDataPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_name: str
    provider_version: str
    interval: str = "1d"
    adjustment_policy: str
    corporate_action_policy: str
    maximum_staleness: timedelta = timedelta(hours=36)
    reject_gaps: bool = True
    warmup_dataset_id: str | None = None
    version: str = "forward-data-v1"


class ForwardRiskPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "forward-risk-v1"
    limits: RiskLimits = Field(default_factory=RiskLimits)
    maximum_strategy_allocation: float = Field(default=0.30, gt=0, le=1)


class ForwardQualificationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "forward-qualification-v1"
    minimum_elapsed_days: int = Field(default=90, ge=1)
    minimum_observations: int = Field(default=60, ge=2)
    minimum_trades: int = Field(default=10, ge=0)
    maximum_drawdown: float = Field(default=0.15, gt=0, le=1)
    minimum_sharpe: float = -0.25
    minimum_excess_return: float = 0.0
    minimum_cost_resilience: float = Field(default=0.70, ge=0, le=1)
    maximum_data_quality_failures: int = Field(default=0, ge=0)
    maximum_risk_breaches: int = Field(default=0, ge=0)


class ForwardDegradationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "forward-degradation-v1"
    rolling_window: int = Field(default=20, ge=5)
    minimum_observations: int = Field(default=20, ge=5)
    warning_sharpe: float = -0.50
    pause_sharpe: float = -1.00
    warning_excess_return: float = -0.05
    pause_excess_return: float = -0.10
    pause_drawdown: float = Field(default=0.12, gt=0, le=1)
    fail_drawdown: float = Field(default=0.20, gt=0, le=1)
    maximum_volatility_ratio: float = Field(default=2.0, gt=1)
    maximum_signal_frequency_ratio: float = Field(default=3.0, gt=1)
    retire_after_failed_evaluations: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "ForwardDegradationPolicy":
        if self.fail_drawdown < self.pause_drawdown:
            raise ValueError("fail drawdown must not be below pause drawdown")
        if self.pause_sharpe > self.warning_sharpe:
            raise ValueError("pause Sharpe must not exceed warning Sharpe")
        if self.pause_excess_return > self.warning_excess_return:
            raise ValueError("pause excess return must not exceed warning threshold")
        return self


class ForwardBaselineProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    annualised_volatility: float = Field(default=0.15, ge=0)
    signal_frequency: float = Field(default=0.10, ge=0, le=1)
    turnover_per_observation: float = Field(default=0.02, ge=0)
    hit_rate: float = Field(default=0.50, ge=0, le=1)
    expectancy: float = 0.0
    source_experiment_id: str | None = None


class ForwardTrialManifest(BaseModel):
    """Frozen configuration. Runtime state is stored separately from this value."""

    model_config = ConfigDict(frozen=True)

    trial_id: str
    portfolio_id: str
    strategy: StrategySpec
    strategy_source_fingerprint: str
    assets: tuple[Asset, ...]
    universe_version: str
    benchmark: ForwardBenchmarkDefinition
    portfolio_starting_capital: float = Field(gt=0)
    allocation_weight: float = Field(gt=0, le=1)
    costs: CostAssumptions
    risk_policy: ForwardRiskPolicy
    data_policy: ForwardDataPolicy
    start_timestamp: datetime
    qualification_policy: ForwardQualificationPolicy
    degradation_policy: ForwardDegradationPolicy
    baseline_profile: ForwardBaselineProfile
    code_revision: str
    random_seed: int = Field(default=1729, ge=0)
    provenance: ObservationProvenance
    created_at: datetime
    configuration_fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        portfolio_id: str,
        strategy: StrategySpec,
        assets: tuple[Asset, ...],
        universe_version: str,
        benchmark: ForwardBenchmarkDefinition,
        portfolio_starting_capital: float,
        allocation_weight: float,
        costs: CostAssumptions,
        risk_policy: ForwardRiskPolicy,
        data_policy: ForwardDataPolicy,
        start_timestamp: datetime,
        qualification_policy: ForwardQualificationPolicy,
        degradation_policy: ForwardDegradationPolicy,
        baseline_profile: ForwardBaselineProfile,
        code_revision: str,
        provenance: ObservationProvenance,
        random_seed: int = 1729,
        created_at: datetime | None = None,
    ) -> "ForwardTrialManifest":
        strategy_hash = strategy_fingerprint(strategy)
        material: dict[str, Any] = {
            "portfolio_id": portfolio_id,
            "strategy": strategy.model_dump(mode="json"),
            "strategy_source_fingerprint": strategy_hash,
            "assets": [asset.model_dump(mode="json") for asset in assets],
            "universe_version": universe_version,
            "benchmark": benchmark.model_dump(mode="json"),
            "portfolio_starting_capital": float(portfolio_starting_capital),
            "allocation_weight": float(allocation_weight),
            "costs": costs.model_dump(mode="json"),
            "risk_policy": risk_policy.model_dump(mode="json"),
            "data_policy": data_policy.model_dump(mode="json"),
            "start_timestamp": start_timestamp.isoformat(),
            "qualification_policy": qualification_policy.model_dump(mode="json"),
            "degradation_policy": degradation_policy.model_dump(mode="json"),
            "baseline_profile": baseline_profile.model_dump(mode="json"),
            "code_revision": code_revision,
            "random_seed": random_seed,
            "provenance": provenance.value,
        }
        fingerprint = canonical_hash(material)
        return cls(
            trial_id=f"forward-{fingerprint[:20]}",
            portfolio_id=portfolio_id,
            strategy=strategy,
            strategy_source_fingerprint=strategy_hash,
            assets=assets,
            universe_version=universe_version,
            benchmark=benchmark,
            portfolio_starting_capital=portfolio_starting_capital,
            allocation_weight=allocation_weight,
            costs=costs,
            risk_policy=risk_policy,
            data_policy=data_policy,
            start_timestamp=start_timestamp,
            qualification_policy=qualification_policy,
            degradation_policy=degradation_policy,
            baseline_profile=baseline_profile,
            code_revision=code_revision,
            random_seed=random_seed,
            provenance=provenance,
            created_at=created_at or datetime.now(UTC),
            configuration_fingerprint=fingerprint,
        )

    def fingerprint_material(self) -> dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "strategy": self.strategy.model_dump(mode="json"),
            "strategy_source_fingerprint": self.strategy_source_fingerprint,
            "assets": [asset.model_dump(mode="json") for asset in self.assets],
            "universe_version": self.universe_version,
            "benchmark": self.benchmark.model_dump(mode="json"),
            "portfolio_starting_capital": self.portfolio_starting_capital,
            "allocation_weight": self.allocation_weight,
            "costs": self.costs.model_dump(mode="json"),
            "risk_policy": self.risk_policy.model_dump(mode="json"),
            "data_policy": self.data_policy.model_dump(mode="json"),
            "start_timestamp": self.start_timestamp.isoformat(),
            "qualification_policy": self.qualification_policy.model_dump(mode="json"),
            "degradation_policy": self.degradation_policy.model_dump(mode="json"),
            "baseline_profile": self.baseline_profile.model_dump(mode="json"),
            "code_revision": self.code_revision,
            "random_seed": self.random_seed,
            "provenance": self.provenance.value,
        }

    @model_validator(mode="after")
    def verify_frozen_fingerprint(self) -> "ForwardTrialManifest":
        if self.start_timestamp.tzinfo is None:
            raise ValueError("forward trial start must be timezone-aware")
        if not self.assets:
            raise ValueError("forward trial requires at least one asset")
        if set(asset.symbol for asset in self.assets) - set(self.strategy.permitted_assets):
            raise ValueError("trial assets must be frozen permitted strategy assets")
        if self.strategy_source_fingerprint != strategy_fingerprint(self.strategy):
            raise ValueError("strategy fingerprint does not match the frozen specification")
        expected = canonical_hash(self.fingerprint_material())
        if self.configuration_fingerprint != expected:
            raise ValueError("forward trial configuration fingerprint mismatch")
        if self.trial_id != f"forward-{expected[:20]}":
            raise ValueError("forward trial ID does not match its frozen configuration")
        if self.allocation_weight > self.risk_policy.maximum_strategy_allocation:
            raise ValueError("trial allocation exceeds the frozen strategy risk budget")
        return self

    @property
    def allocated_capital(self) -> float:
        return self.portfolio_starting_capital * self.allocation_weight


class ForwardTrial(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest: ForwardTrialManifest
    state: ForwardTrialState = ForwardTrialState.READY_FOR_FORWARD
    started_at: datetime
    updated_at: datetime
    failed_evaluations: int = 0
    latest_observation_at: datetime | None = None


class ForwardEvidenceInstrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Asset
    rows: int
    actual_start: datetime
    actual_end: datetime
    raw_checksum: str
    canonical_checksum: str
    artifact: str
    warnings: tuple[str, ...] = ()


class ForwardEvidenceManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_id: str
    stream_id: str
    sequence: int = Field(ge=1)
    previous_manifest_id: str | None
    provenance: ObservationProvenance
    source_dataset_id: str | None = None
    provider_name: str
    provider_version: str
    interval: str
    requested_start: datetime
    requested_end: datetime
    fetched_at: datetime
    instruments: tuple[ForwardEvidenceInstrument, ...]
    code_revision: str
    manifest_checksum: str


class IncrementalEvidenceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest: ForwardEvidenceManifest | None
    new_bars: dict[str, tuple[MarketBar, ...]]
    created: bool
    warnings: tuple[str, ...] = ()


class ForwardObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str
    trial_id: str
    cycle_id: str
    evidence_manifest_id: str
    provenance: ObservationProvenance
    bar: MarketBar
    available_at: datetime
    regime: str | None = None


class ForwardSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: str
    trial_id: str
    cycle_id: str
    timestamp: datetime
    desired_exposure: float = Field(ge=0, le=1)
    regime: str | None = None


class ForwardPendingOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str
    order: SimulatedOrder


class ForwardFill(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str
    fill: SimulatedFill


class ForwardPosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Asset
    quantity: float = Field(gt=0)
    average_price: float = Field(gt=0)
    entry_timestamp: datetime
    entry_fees: float = Field(default=0.0, ge=0)


class ForwardTrialLedger(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str
    starting_cash: float = Field(gt=0)
    cash: float = Field(ge=0)
    positions: dict[str, ForwardPosition] = Field(default_factory=dict)
    realised_pnl: float = 0.0
    fees_paid: float = Field(default=0.0, ge=0)
    turnover_notional: float = Field(default=0.0, ge=0)
    signal_count: int = Field(default=0, ge=0)
    trades: tuple[Trade, ...] = ()


class ForwardPortfolioState(BaseModel):
    model_config = ConfigDict(frozen=True)

    portfolio_id: str
    starting_capital: float = Field(gt=0)
    reserve_cash: float = Field(ge=0)
    ledgers: dict[str, ForwardTrialLedger]
    pending_orders: tuple[ForwardPendingOrder, ...] = ()
    latest_prices: dict[str, float] = Field(default_factory=dict)
    peak_equity: float = Field(gt=0)
    risk_period_date: str | None = None
    period_turnover: float = Field(default=0.0, ge=0)
    period_trades: int = Field(default=0, ge=0)
    last_cycle_id: str | None = None


class ForwardTrialSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str
    timestamp: datetime
    cash: float
    market_value: float
    equity: float
    realised_pnl: float
    unrealised_pnl: float
    drawdown: float
    allocation: float


class ForwardPortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    portfolio_id: str
    cycle_id: str
    provenance: ObservationProvenance
    timestamp: datetime
    cash: float
    market_value: float
    equity: float
    drawdown: float
    gross_exposure: float
    positions: dict[str, dict[str, Any]]
    trial_snapshots: tuple[ForwardTrialSnapshot, ...]
    asset_class_exposure: dict[str, float]


class ForwardPortfolioStepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: ForwardPortfolioState
    snapshot: ForwardPortfolioSnapshot
    signals: tuple[ForwardSignal, ...]
    orders: tuple[ForwardPendingOrder, ...]
    fills: tuple[ForwardFill, ...]
    trades: dict[str, tuple[Trade, ...]]
    risk_rejections: dict[str, tuple[str, ...]]


class ForwardPerformance(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str
    observations: int
    elapsed_days: int
    total_return: float
    annualised_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    maximum_drawdown: float
    benchmark_return: float
    excess_return: float
    hit_rate: float
    expectancy: float
    turnover: float
    costs: float
    cost_resilience: float
    signal_frequency: float
    trades: int
    regime_mix: dict[str, int]


class ForwardDriftDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str
    timestamp: datetime
    window: int
    rolling_return: float
    rolling_volatility: float
    rolling_sharpe: float
    rolling_sortino: float
    rolling_drawdown: float
    benchmark_relative_return: float
    hit_rate: float
    expectancy: float
    turnover_per_observation: float
    cost_ratio: float
    signal_frequency: float
    volatility_ratio: float
    signal_frequency_ratio: float
    regime_mix: dict[str, int]
    data_age_seconds: float
    severity: DegradationSeverity
    reasons: tuple[str, ...]


class ForwardLifecycleDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str
    trial_id: str
    cycle_id: str
    timestamp: datetime
    previous_state: ForwardTrialState
    new_state: ForwardTrialState
    rule_id: str
    reasons: tuple[str, ...]
    evidence: dict[str, Any]


class ForwardDataQualityEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    cycle_id: str
    trial_id: str | None = None
    timestamp: datetime
    event_type: str
    severity: str
    detail: str
    resolved: bool = False


class ForwardCycleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    cycle_id: str
    portfolio_id: str
    evidence_manifest_id: str
    provenance: ObservationProvenance
    status: ForwardCycleStatus
    processed: bool
    timestamp: datetime
    observations: tuple[ForwardObservation, ...] = ()
    signals: tuple[ForwardSignal, ...] = ()
    orders: tuple[ForwardPendingOrder, ...] = ()
    fills: tuple[ForwardFill, ...] = ()
    snapshot: ForwardPortfolioSnapshot | None = None
    lifecycle_decisions: tuple[ForwardLifecycleDecision, ...] = ()
    degradation: tuple[ForwardDriftDiagnostic, ...] = ()
    data_quality: tuple[ForwardDataQualityEvent, ...] = ()
    risk_rejections: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    error: str | None = None


class ChampionChallengerComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    champion_trial_id: str | None
    ranking: tuple[str, ...]
    performance: dict[str, ForwardPerformance]
    pairwise_return_correlation: dict[str, dict[str, float]]
    overlapping_exposure: dict[str, float]
    drawdown_contribution: dict[str, float]
    qualification_note: str = (
        "Ranking is a paper-observation comparison and never authorises live execution."
    )
