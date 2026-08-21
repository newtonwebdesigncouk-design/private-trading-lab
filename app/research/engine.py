"""Generates explainable candidates without modifying executable source code."""

import hashlib
import json
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from app.backtesting import BacktestEngine, BacktestResult
from app.models.enums import StrategyState
from app.models.market import MarketBar
from app.models.strategy import IndicatorSpec, StrategySpec
from app.research.experiments import ExperimentRecord
from app.scoring import StrategyScore, score_strategy
from app.strategies.reference import strategy_from_spec


class CandidateReason(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_version: str
    parent_strategy: str
    parameter_changes: dict[str, float | int | str | bool]
    indicator_names: tuple[str, ...] = ()
    reason: str


class ApprovedStrategyVariation(BaseModel):
    """A bounded parameter/indicator change supplied by an owner-controlled catalogue."""

    model_config = ConfigDict(frozen=True)

    parameter_changes: dict[str, float | int | str | bool]
    indicators: tuple[IndicatorSpec, ...]
    reason: str


class CandidateEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: StrategySpec
    creation: CandidateReason
    backtest: BacktestResult
    score: StrategyScore
    retained: bool
    decision_reason: str
    experiment: ExperimentRecord


class ResearchBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    parent_strategy: str
    dataset_id: str
    evaluations: tuple[CandidateEvaluation, ...]

    @property
    def retained(self) -> tuple[CandidateEvaluation, ...]:
        return tuple(evaluation for evaluation in self.evaluations if evaluation.retained)

    @property
    def rejected(self) -> tuple[CandidateEvaluation, ...]:
        return tuple(evaluation for evaluation in self.evaluations if not evaluation.retained)


class BoundedResearchEngine:
    """Creates specs from approved parameter grids; it cannot write application code."""

    def __init__(self, *, maximum_candidates: int = 50) -> None:
        if maximum_candidates <= 0:
            raise ValueError("maximum_candidates must be positive")
        self.maximum_candidates = maximum_candidates

    def generate_candidates(
        self,
        parent: StrategySpec,
        parameter_grid: Mapping[str, Sequence[float | int]],
    ) -> tuple[tuple[StrategySpec, CandidateReason], ...]:
        generated: list[tuple[StrategySpec, CandidateReason]] = []
        for parameter in sorted(parameter_grid):
            if parameter not in parent.parameters:
                raise ValueError(f"parameter is not approved by parent spec: {parameter}")
            for value in parameter_grid[parameter]:
                if len(generated) >= self.maximum_candidates:
                    return tuple(generated)
                parameters = dict(parent.parameters)
                old_value = parameters[parameter]
                parameters[parameter] = value
                change = {parameter: value}
                digest = hashlib.sha256(
                    f"{parent.version_key}|{parameter}|{value}".encode()
                ).hexdigest()[:8]
                reason_text = f"Bounded variation of {parameter}: {old_value} -> {value}"
                candidate = StrategySpec.model_validate(
                    {
                        **parent.model_dump(mode="python"),
                        "strategy_id": f"{parent.strategy_id}-candidate-{digest}",
                        "version": 1,
                        "parameters": parameters,
                        "creation_method": "bounded_parameter_search",
                        "creation_reason": reason_text,
                        "parent_strategy": parent.version_key,
                        "state": StrategyState.CREATED,
                    },
                )
                reason = CandidateReason(
                    candidate_version=candidate.version_key,
                    parent_strategy=parent.version_key,
                    parameter_changes=change,
                    indicator_names=tuple(indicator.name for indicator in candidate.indicators),
                    reason=reason_text,
                )
                generated.append((candidate, reason))
        return tuple(generated)

    def generate_approved_variations(
        self,
        parent: StrategySpec,
        variations: Sequence[ApprovedStrategyVariation],
        *,
        approved_indicator_names: frozenset[str],
    ) -> tuple[tuple[StrategySpec, CandidateReason], ...]:
        """Create candidates only from explicitly approved parameter keys and indicators."""
        generated: list[tuple[StrategySpec, CandidateReason]] = []
        for variation in variations[: self.maximum_candidates]:
            unknown_parameters = set(variation.parameter_changes).difference(parent.parameters)
            if unknown_parameters:
                names = ", ".join(sorted(unknown_parameters))
                raise ValueError(f"parameters are not approved by parent spec: {names}")
            unknown_indicators = {
                indicator.name
                for indicator in variation.indicators
                if indicator.name not in approved_indicator_names
            }
            if unknown_indicators:
                names = ", ".join(sorted(unknown_indicators))
                raise ValueError(f"indicators are not in the approved catalogue: {names}")
            parameters = {**parent.parameters, **variation.parameter_changes}
            fingerprint = json.dumps(
                {
                    "parameters": variation.parameter_changes,
                    "indicators": [
                        indicator.model_dump(mode="json") for indicator in variation.indicators
                    ],
                },
                sort_keys=True,
            )
            digest = hashlib.sha256(f"{parent.version_key}|{fingerprint}".encode()).hexdigest()[:8]
            candidate = StrategySpec.model_validate(
                {
                    **parent.model_dump(mode="python"),
                    "strategy_id": f"{parent.strategy_id}-candidate-{digest}",
                    "version": 1,
                    "parameters": parameters,
                    "indicators": variation.indicators,
                    "creation_method": "bounded_approved_variation",
                    "creation_reason": variation.reason,
                    "parent_strategy": parent.version_key,
                    "state": StrategyState.CREATED,
                }
            )
            reason = CandidateReason(
                candidate_version=candidate.version_key,
                parent_strategy=parent.version_key,
                parameter_changes=variation.parameter_changes,
                indicator_names=tuple(indicator.name for indicator in variation.indicators),
                reason=variation.reason,
            )
            generated.append((candidate, reason))
        return tuple(generated)

    def evaluate_candidates(
        self,
        parent: StrategySpec,
        parameter_grid: Mapping[str, Sequence[float | int]],
        bars: Sequence[MarketBar],
        *,
        dataset_id: str,
        backtest_engine: BacktestEngine,
        code_version: str,
        random_seed: int,
        retention_score: float = 50.0,
        out_of_sample_validated: bool = False,
    ) -> ResearchBatchResult:
        """Backtest, score and record bounded candidates without mutating executable code."""
        return self._evaluate_generated(
            parent,
            self.generate_candidates(parent, parameter_grid),
            bars,
            dataset_id=dataset_id,
            backtest_engine=backtest_engine,
            code_version=code_version,
            random_seed=random_seed,
            retention_score=retention_score,
            out_of_sample_validated=out_of_sample_validated,
        )

    def evaluate_approved_variations(
        self,
        parent: StrategySpec,
        variations: Sequence[ApprovedStrategyVariation],
        bars: Sequence[MarketBar],
        *,
        approved_indicator_names: frozenset[str],
        dataset_id: str,
        backtest_engine: BacktestEngine,
        code_version: str,
        random_seed: int,
        retention_score: float = 50.0,
        out_of_sample_validated: bool = False,
    ) -> ResearchBatchResult:
        """Evaluate owner-approved parameter/indicator combinations as reproducible experiments."""
        return self._evaluate_generated(
            parent,
            self.generate_approved_variations(
                parent,
                variations,
                approved_indicator_names=approved_indicator_names,
            ),
            bars,
            dataset_id=dataset_id,
            backtest_engine=backtest_engine,
            code_version=code_version,
            random_seed=random_seed,
            retention_score=retention_score,
            out_of_sample_validated=out_of_sample_validated,
        )

    def _evaluate_generated(
        self,
        parent: StrategySpec,
        generated: Sequence[tuple[StrategySpec, CandidateReason]],
        bars: Sequence[MarketBar],
        *,
        dataset_id: str,
        backtest_engine: BacktestEngine,
        code_version: str,
        random_seed: int,
        retention_score: float,
        out_of_sample_validated: bool,
    ) -> ResearchBatchResult:
        if not 0 <= retention_score <= 100:
            raise ValueError("retention_score must lie in [0, 100]")
        if len(bars) < 2:
            raise ValueError("at least two bars are required to evaluate research candidates")

        evaluations: list[CandidateEvaluation] = []
        for candidate, creation in generated:
            candidate_dataset = f"{dataset_id}:{candidate.version_key}"
            result = backtest_engine.run(
                strategy_from_spec(candidate), bars, dataset_id=candidate_dataset
            )
            score = score_strategy(
                result,
                parameter_stability=0.5,
                out_of_sample_validated=out_of_sample_validated,
            )
            retained = score.score >= retention_score and score.state is not StrategyState.REJECTED
            if retained:
                decision_reason = "retained for further validation"
            else:
                reasons = list(score.reasons)
                if score.score < retention_score:
                    reasons.append(
                        f"score {score.score:.2f} is below retention threshold "
                        f"{retention_score:.2f}"
                    )
                decision_reason = "; ".join(reasons) or "strategy was rejected by lifecycle rules"
            experiment_digest = hashlib.sha256(
                (
                    f"{candidate.version_key}|{candidate_dataset}|{code_version}|{random_seed}"
                ).encode()
            ).hexdigest()
            experiment = ExperimentRecord(
                experiment_id=experiment_digest,
                strategy_version=candidate.version_key,
                dataset_version=candidate_dataset,
                instruments=(bars[0].asset.symbol,),
                period_start=bars[0].timestamp,
                period_end=bars[-1].timestamp,
                transaction_cost_assumptions=result.costs.model_dump(mode="json"),
                parameters=dict(candidate.parameters),
                code_version=code_version,
                random_seed=random_seed,
                metrics=result.metrics.model_dump(mode="json"),
                validation_result=score.state.value,
                rejection_reason=None if retained else decision_reason,
            )
            evaluations.append(
                CandidateEvaluation(
                    candidate=candidate,
                    creation=creation,
                    backtest=result,
                    score=score,
                    retained=retained,
                    decision_reason=decision_reason,
                    experiment=experiment,
                )
            )
        return ResearchBatchResult(
            parent_strategy=parent.version_key,
            dataset_id=dataset_id,
            evaluations=tuple(evaluations),
        )
