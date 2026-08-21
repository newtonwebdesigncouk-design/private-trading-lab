"""Conservative paper-observation gate; zero qualifying strategies is valid."""

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import StrategyState


class QualificationRequirements(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum_score: float = Field(default=75.0, ge=0, le=100)
    minimum_out_of_sample_bars: int = Field(default=252, ge=2)
    minimum_trades: int = Field(default=30, ge=1)
    maximum_drawdown: float = Field(default=0.15, gt=0, le=1)
    minimum_cost_stress_ratio: float = Field(default=0.80, ge=0, le=1)
    minimum_parameter_stability: float = Field(default=0.70, ge=0, le=1)
    minimum_profitable_walk_forward_fraction: float = Field(default=0.60, ge=0, le=1)
    require_benchmark_outperformance: bool = True


class QualificationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float
    out_of_sample_bars: int
    trades: int
    maximum_drawdown: float
    cost_stress_ratio: float
    parameter_stability: float
    profitable_walk_forward_fraction: float
    benchmark_excess_return: float
    final_holdout_isolated: bool
    critical_warnings: tuple[str, ...] = ()


class QualificationDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    qualified: bool
    state: StrategyState
    reasons: tuple[str, ...]


def evaluate_paper_qualification(
    evidence: QualificationEvidence,
    requirements: QualificationRequirements | None = None,
) -> QualificationDecision:
    policy = requirements or QualificationRequirements()
    reasons: list[str] = []
    if evidence.score < policy.minimum_score:
        reasons.append("score below paper qualification minimum")
    if evidence.out_of_sample_bars < policy.minimum_out_of_sample_bars:
        reasons.append("insufficient out-of-sample history")
    if evidence.trades < policy.minimum_trades:
        reasons.append("insufficient trade sample")
    if evidence.maximum_drawdown > policy.maximum_drawdown:
        reasons.append("maximum drawdown exceeds qualification limit")
    if evidence.cost_stress_ratio < policy.minimum_cost_stress_ratio:
        reasons.append("cost-stress result is not robust")
    if evidence.parameter_stability < policy.minimum_parameter_stability:
        reasons.append("parameter neighbourhood is unstable")
    if evidence.profitable_walk_forward_fraction < policy.minimum_profitable_walk_forward_fraction:
        reasons.append("walk-forward consistency is insufficient")
    if policy.require_benchmark_outperformance and evidence.benchmark_excess_return <= 0:
        reasons.append("did not outperform the configured passive benchmark")
    if not evidence.final_holdout_isolated:
        reasons.append("final hold-out isolation was not proven")
    reasons.extend(evidence.critical_warnings)
    return QualificationDecision(
        qualified=not reasons,
        state=StrategyState.PAPER_ELIGIBLE if not reasons else StrategyState.VALIDATION,
        reasons=tuple(reasons),
    )
