"""Frozen, explainable forward qualification, pause, fail, and retirement rules."""

from datetime import datetime

from app.forward.models import (
    ForwardDriftDiagnostic,
    ForwardLifecycleDecision,
    ForwardPerformance,
    ForwardTrial,
    canonical_hash,
)
from app.models.enums import DegradationSeverity, ForwardTrialState


def _decision(
    trial: ForwardTrial,
    cycle_id: str,
    timestamp: datetime,
    new_state: ForwardTrialState,
    rule_id: str,
    reasons: tuple[str, ...],
    evidence: dict[str, object],
) -> ForwardLifecycleDecision:
    identity = {
        "trial_id": trial.manifest.trial_id,
        "cycle_id": cycle_id,
        "previous_state": trial.state.value,
        "new_state": new_state.value,
        "rule_id": rule_id,
        "reasons": reasons,
        "evidence": evidence,
    }
    return ForwardLifecycleDecision(
        decision_id=f"forward-decision-{canonical_hash(identity)[:24]}",
        trial_id=trial.manifest.trial_id,
        cycle_id=cycle_id,
        timestamp=timestamp,
        previous_state=trial.state,
        new_state=new_state,
        rule_id=rule_id,
        reasons=reasons,
        evidence=evidence,
    )


def evaluate_forward_lifecycle(
    trial: ForwardTrial,
    performance: ForwardPerformance,
    drift: ForwardDriftDiagnostic,
    *,
    cycle_id: str,
    timestamp: datetime,
    unresolved_data_quality_failures: int = 0,
    risk_breaches: int = 0,
) -> ForwardLifecycleDecision:
    """Apply only thresholds frozen in the trial manifest; zero qualification is valid."""
    manifest = trial.manifest
    qualification = manifest.qualification_policy
    degradation = manifest.degradation_policy
    common_evidence: dict[str, object] = {
        "observations": performance.observations,
        "elapsed_days": performance.elapsed_days,
        "trades": performance.trades,
        "maximum_drawdown": performance.maximum_drawdown,
        "sharpe_ratio": performance.sharpe_ratio,
        "excess_return": performance.excess_return,
        "cost_resilience": performance.cost_resilience,
        "data_quality_failures": unresolved_data_quality_failures,
        "risk_breaches": risk_breaches,
        "qualification_policy_version": qualification.version,
        "degradation_policy_version": degradation.version,
        "qualified_forward_meaning": "paper observation only; no live execution approval",
    }
    if trial.state is ForwardTrialState.RETIRED:
        return _decision(
            trial,
            cycle_id,
            timestamp,
            ForwardTrialState.RETIRED,
            "RETIRED_TERMINAL",
            ("retired trials remain immutable and terminal",),
            common_evidence,
        )
    if (
        trial.state is ForwardTrialState.FAILED_FORWARD
        and trial.failed_evaluations + 1 >= degradation.retire_after_failed_evaluations
    ):
        return _decision(
            trial,
            cycle_id,
            timestamp,
            ForwardTrialState.RETIRED,
            "AUTOMATIC_RETIREMENT",
            ("frozen consecutive failed-evaluation limit reached",),
            common_evidence,
        )
    if unresolved_data_quality_failures > qualification.maximum_data_quality_failures:
        return _decision(
            trial,
            cycle_id,
            timestamp,
            ForwardTrialState.PAUSED_DATA_QUALITY,
            "DATA_QUALITY_PAUSE",
            ("unresolved forward data-quality failures exceed the frozen allowance",),
            common_evidence,
        )
    if risk_breaches > qualification.maximum_risk_breaches:
        return _decision(
            trial,
            cycle_id,
            timestamp,
            ForwardTrialState.PAUSED_RISK,
            "RISK_BREACH_PAUSE",
            ("paper portfolio risk breaches exceed the frozen allowance",),
            common_evidence,
        )
    if drift.severity is DegradationSeverity.FAIL:
        return _decision(
            trial,
            cycle_id,
            timestamp,
            ForwardTrialState.FAILED_FORWARD,
            "DEGRADATION_FAIL",
            drift.reasons,
            common_evidence,
        )
    if drift.severity is DegradationSeverity.PAUSE:
        return _decision(
            trial,
            cycle_id,
            timestamp,
            ForwardTrialState.PAUSED_RISK,
            "DEGRADATION_PAUSE",
            drift.reasons,
            common_evidence,
        )
    enough_elapsed = performance.elapsed_days >= qualification.minimum_elapsed_days
    enough_observations = performance.observations >= qualification.minimum_observations
    enough_trades = performance.trades >= qualification.minimum_trades
    if enough_observations and performance.maximum_drawdown > qualification.maximum_drawdown:
        return _decision(
            trial,
            cycle_id,
            timestamp,
            ForwardTrialState.FAILED_FORWARD,
            "FORWARD_DRAWDOWN_FAIL",
            ("maximum forward drawdown breached the frozen qualification limit",),
            common_evidence,
        )
    missing: list[str] = []
    if not enough_elapsed:
        missing.append("minimum elapsed observation period not met")
    if not enough_observations:
        missing.append("minimum independent observations not met")
    if not enough_trades:
        missing.append("minimum completed trade count not met")
    if performance.maximum_drawdown > qualification.maximum_drawdown:
        missing.append("maximum drawdown requirement not met")
    if performance.sharpe_ratio < qualification.minimum_sharpe:
        missing.append("minimum Sharpe requirement not met")
    if performance.excess_return < qualification.minimum_excess_return:
        missing.append("frozen benchmark-relative requirement not met")
    if performance.cost_resilience < qualification.minimum_cost_resilience:
        missing.append("minimum cost resilience not met")
    if missing:
        return _decision(
            trial,
            cycle_id,
            timestamp,
            ForwardTrialState.OBSERVING,
            "MINIMUM_EVIDENCE_PENDING",
            tuple(missing),
            common_evidence,
        )
    return _decision(
        trial,
        cycle_id,
        timestamp,
        ForwardTrialState.QUALIFIED_FORWARD,
        "QUALIFIED_FORWARD_PAPER_ONLY",
        ("all frozen Phase 3 paper-observation requirements are satisfied",),
        common_evidence,
    )
