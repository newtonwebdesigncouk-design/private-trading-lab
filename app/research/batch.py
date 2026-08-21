"""Deterministic cartesian/random bounded research with a locked final hold-out."""

import hashlib
import random
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from app.backtesting import BacktestConfig, BacktestEngine, BacktestResult, CostAssumptions
from app.models.enums import StrategyState
from app.models.market import MarketBar
from app.models.strategy import StrategySpec
from app.scoring import score_strategy
from app.strategies.reference import strategy_from_spec
from app.validation.multiple_testing import (
    MultipleTestingDiagnostic,
    approximate_sharpe_p_value,
    benjamini_hochberg,
)
from app.validation.splits import chronological_split


class BatchCandidateEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: StrategySpec
    train_results: dict[str, BacktestResult]
    validation_results: dict[str, BacktestResult]
    mean_validation_score: float
    mean_validation_sharpe: float
    validation_trades: int
    cost_stress_ratio: float
    p_value: float
    selected_for_holdout: bool = False
    reasons: tuple[str, ...] = ()


class BatchResearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    batch_id: str
    dataset_id: str
    universe_version: str
    random_seed: int
    random_search: bool
    candidate_space_size: int
    candidate_count: int
    holdout_locked: bool = True
    holdout_periods: dict[str, tuple[object, object]]
    evaluations: tuple[BatchCandidateEvaluation, ...]
    multiple_testing: MultipleTestingDiagnostic
    selected_candidate_versions: tuple[str, ...]


class LockedHoldoutEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_version: str
    instrument_results: dict[str, BacktestResult]
    mean_score: float


class Phase2BatchResearchEngine:
    def __init__(self, *, maximum_candidates: int = 500) -> None:
        if maximum_candidates <= 0:
            raise ValueError("maximum_candidates must be positive")
        self.maximum_candidates = maximum_candidates

    @staticmethod
    def _combination_at(
        values: Sequence[Sequence[float | int]], index: int
    ) -> tuple[float | int, ...]:
        selected: list[float | int] = []
        for dimension in reversed(values):
            selected.append(dimension[index % len(dimension)])
            index //= len(dimension)
        return tuple(reversed(selected))

    def generate_cartesian_candidates(
        self,
        parent: StrategySpec,
        parameter_grid: Mapping[str, Sequence[float | int]],
        *,
        random_seed: int,
        random_search: bool = False,
    ) -> tuple[int, tuple[StrategySpec, ...]]:
        names = tuple(sorted(parameter_grid))
        if any(name not in parent.parameters for name in names):
            unknown = sorted(set(names).difference(parent.parameters))
            raise ValueError(f"parameters are not approved by parent spec: {', '.join(unknown)}")
        values = tuple(tuple(parameter_grid[name]) for name in names)
        if any(not dimension for dimension in values):
            raise ValueError("parameter dimensions cannot be empty")
        space_size = 1
        for dimension in values:
            space_size *= len(dimension)
        count = min(space_size, self.maximum_candidates)
        if random_search and space_size > count:
            indices = sorted(random.Random(random_seed).sample(range(space_size), count))
        else:
            indices = list(range(count))
        candidates: list[StrategySpec] = []
        for index in indices:
            combination = self._combination_at(values, index) if values else ()
            changes = dict(zip(names, combination, strict=True))
            parameters = {**parent.parameters, **changes}
            fingerprint = "|".join(f"{name}={parameters[name]}" for name in names)
            digest = hashlib.sha256(f"{parent.version_key}|{fingerprint}".encode()).hexdigest()[:12]
            candidates.append(
                StrategySpec.model_validate(
                    {
                        **parent.model_dump(mode="python"),
                        "strategy_id": f"{parent.strategy_id}-batch-{digest}",
                        "version": 1,
                        "parameters": parameters,
                        "creation_method": (
                            "bounded_seeded_random_search"
                            if random_search
                            else "bounded_cartesian_search"
                        ),
                        "creation_reason": f"Approved Phase 2 batch variation: {fingerprint}",
                        "parent_strategy": parent.version_key,
                        "state": StrategyState.CREATED,
                    }
                )
            )
        return space_size, tuple(sorted(candidates, key=lambda item: item.version_key))

    def run_selection(
        self,
        parent: StrategySpec,
        parameter_grid: Mapping[str, Sequence[float | int]],
        bars_by_symbol: Mapping[str, Sequence[MarketBar]],
        *,
        dataset_id: str,
        universe_version: str,
        random_seed: int,
        backtest_config: BacktestConfig | None = None,
        random_search: bool = False,
        retention_score: float = 70.0,
        minimum_validation_trades: int = 10,
        false_discovery_rate: float = 0.05,
    ) -> BatchResearchResult:
        if not bars_by_symbol:
            raise ValueError("at least one instrument is required")
        if not 0 <= retention_score <= 100:
            raise ValueError("retention_score must lie in [0, 100]")
        space_size, candidates = self.generate_cartesian_candidates(
            parent,
            parameter_grid,
            random_seed=random_seed,
            random_search=random_search,
        )
        partitions = {
            symbol: chronological_split(bars) for symbol, bars in sorted(bars_by_symbol.items())
        }
        holdout_periods = {
            symbol: (parts[2][0].timestamp, parts[2][-1].timestamp)
            for symbol, parts in partitions.items()
        }
        config = backtest_config or BacktestConfig()
        engine = BacktestEngine(config)
        stressed_costs = CostAssumptions(
            commission_bps=config.costs.commission_bps * 2,
            fixed_fee=config.costs.fixed_fee * 2,
            minimum_commission=config.costs.minimum_commission * 2,
            spread_bps=config.costs.spread_bps * 2,
            slippage_bps=config.costs.slippage_bps * 2,
        )
        stressed_engine = BacktestEngine(config.model_copy(update={"costs": stressed_costs}))
        evaluations: list[BatchCandidateEvaluation] = []
        p_values: dict[str, float] = {}
        for candidate in candidates:
            train_results: dict[str, BacktestResult] = {}
            validation_results: dict[str, BacktestResult] = {}
            scores: list[float] = []
            sharpes: list[float] = []
            validation_trades = 0
            normal_returns: list[float] = []
            stressed_returns: list[float] = []
            reasons: list[str] = []
            for symbol, (train, validation, _locked_holdout) in partitions.items():
                instrument_spec = candidate.model_copy(
                    update={
                        "permitted_assets": (symbol,),
                        "asset_class": validation[0].asset.asset_class,
                    }
                )
                strategy = strategy_from_spec(instrument_spec)
                train_result = engine.run(
                    strategy,
                    train,
                    dataset_id=f"{dataset_id}:{candidate.version_key}:{symbol}:train",
                )
                validation_result = engine.run(
                    strategy,
                    validation,
                    dataset_id=f"{dataset_id}:{candidate.version_key}:{symbol}:validation",
                )
                stressed_result = stressed_engine.run(
                    strategy,
                    validation,
                    dataset_id=f"{dataset_id}:{candidate.version_key}:{symbol}:cost-stress",
                )
                train_results[symbol] = train_result
                validation_results[symbol] = validation_result
                candidate_score = score_strategy(
                    validation_result,
                    parameter_stability=0.5,
                    out_of_sample_validated=False,
                )
                scores.append(candidate_score.score)
                sharpes.append(validation_result.metrics.sharpe_ratio)
                validation_trades += validation_result.metrics.number_of_trades
                normal_returns.append(validation_result.metrics.total_return)
                stressed_returns.append(stressed_result.metrics.total_return)
            mean_score = sum(scores) / len(scores)
            mean_sharpe = sum(sharpes) / len(sharpes)
            normal_total = sum(normal_returns)
            stressed_total = sum(stressed_returns)
            cost_stress_ratio = (
                stressed_total / normal_total
                if normal_total > 0
                else (1.0 if stressed_total >= 0 else 0.0)
            )
            if mean_score < retention_score:
                reasons.append("mean validation score below research threshold")
            if validation_trades < minimum_validation_trades:
                reasons.append("minimum validation trade count not met")
            if any(result.benchmark.excess_return <= 0 for result in validation_results.values()):
                reasons.append("failed to beat every instrument passive benchmark")
            if cost_stress_ratio < 0.80:
                reasons.append("performance is too sensitive to doubled costs")
            observations = sum(len(parts[1]) for parts in partitions.values())
            p_value = approximate_sharpe_p_value(mean_sharpe, observations)
            p_values[candidate.version_key] = p_value
            evaluations.append(
                BatchCandidateEvaluation(
                    candidate=candidate,
                    train_results=train_results,
                    validation_results=validation_results,
                    mean_validation_score=mean_score,
                    mean_validation_sharpe=mean_sharpe,
                    validation_trades=validation_trades,
                    cost_stress_ratio=cost_stress_ratio,
                    p_value=p_value,
                    reasons=tuple(reasons),
                )
            )
        diagnostic = benjamini_hochberg(p_values, alpha=false_discovery_rate)
        discoveries = set(diagnostic.discoveries)
        final_evaluations = tuple(
            evaluation.model_copy(
                update={
                    "selected_for_holdout": (
                        not evaluation.reasons and evaluation.candidate.version_key in discoveries
                    ),
                    "reasons": evaluation.reasons
                    + (
                        ()
                        if evaluation.candidate.version_key in discoveries
                        else ("failed false-discovery diagnostic",)
                    ),
                }
            )
            for evaluation in evaluations
        )
        batch_raw = (
            f"{dataset_id}|{universe_version}|{parent.version_key}|{random_seed}|"
            f"{random_search}|{','.join(item.candidate.version_key for item in final_evaluations)}"
        )
        return BatchResearchResult(
            batch_id=hashlib.sha256(batch_raw.encode()).hexdigest(),
            dataset_id=dataset_id,
            universe_version=universe_version,
            random_seed=random_seed,
            random_search=random_search,
            candidate_space_size=space_size,
            candidate_count=len(final_evaluations),
            holdout_periods=holdout_periods,
            evaluations=final_evaluations,
            multiple_testing=diagnostic,
            selected_candidate_versions=tuple(
                evaluation.candidate.version_key
                for evaluation in final_evaluations
                if evaluation.selected_for_holdout
            ),
        )

    def evaluate_selected_holdout(
        self,
        batch: BatchResearchResult,
        bars_by_symbol: Mapping[str, Sequence[MarketBar]],
        *,
        backtest_config: BacktestConfig | None = None,
    ) -> tuple[LockedHoldoutEvaluation, ...]:
        """Open the final hold-out only after selection; results cannot change the selection set."""
        if not batch.holdout_locked:
            raise ValueError("research batch did not preserve hold-out isolation")
        selected = set(batch.selected_candidate_versions)
        candidates = {
            item.candidate.version_key: item.candidate
            for item in batch.evaluations
            if item.candidate.version_key in selected
        }
        engine = BacktestEngine(backtest_config or BacktestConfig())
        evaluations: list[LockedHoldoutEvaluation] = []
        for version in sorted(selected):
            candidate = candidates[version]
            results: dict[str, BacktestResult] = {}
            scores: list[float] = []
            for symbol, bars in sorted(bars_by_symbol.items()):
                _train, _validation, holdout = chronological_split(bars)
                spec = candidate.model_copy(
                    update={
                        "permitted_assets": (symbol,),
                        "asset_class": holdout[0].asset.asset_class,
                    }
                )
                result = engine.run(
                    strategy_from_spec(spec),
                    holdout,
                    dataset_id=f"{batch.dataset_id}:{version}:{symbol}:locked-holdout",
                )
                results[symbol] = result
                scores.append(
                    score_strategy(
                        result,
                        parameter_stability=0.5,
                        out_of_sample_validated=True,
                    ).score
                )
            evaluations.append(
                LockedHoldoutEvaluation(
                    candidate_version=version,
                    instrument_results=results,
                    mean_score=sum(scores) / len(scores),
                )
            )
        return tuple(evaluations)
