"""GET-only operational read models for the Phase 3 dashboard/API."""

from collections import Counter
from datetime import UTC, datetime

from app.backtesting.analytics import periodic_returns
from app.forward.analytics import compare_champion_challengers
from app.forward.repository import ForwardRepository
from app.models.enums import ForwardCycleStatus, ObservationProvenance


class ForwardReadModel:
    def __init__(self, repository: ForwardRepository, *, kill_switch: bool) -> None:
        self.repository = repository
        self.kill_switch = kill_switch

    @staticmethod
    def _trial_item(trial: object) -> dict[str, object]:
        from app.forward.models import ForwardTrial

        if not isinstance(trial, ForwardTrial):
            raise TypeError("expected a forward trial")
        policy = trial.manifest.qualification_policy
        return {
            "trial_id": trial.manifest.trial_id,
            "portfolio_id": trial.manifest.portfolio_id,
            "strategy_version": trial.manifest.strategy.version_key,
            "state": trial.state.value,
            "provenance": trial.manifest.provenance.value,
            "start_timestamp": trial.manifest.start_timestamp,
            "latest_observation_at": trial.latest_observation_at,
            "configuration_fingerprint": trial.manifest.configuration_fingerprint,
            "allocation_weight": trial.manifest.allocation_weight,
            "benchmark": trial.manifest.benchmark.model_dump(mode="json"),
            "minimum_evidence": {
                "elapsed_days": policy.minimum_elapsed_days,
                "observations": policy.minimum_observations,
                "trades": policy.minimum_trades,
            },
            "qualification_meaning": "PAPER qualification only; no live execution approval",
        }

    def trials(self) -> dict[str, object]:
        trials = self.repository.list_trials()
        states = Counter(item.state.value for item in trials)
        return {
            "items": [self._trial_item(item) for item in trials],
            "counts": dict(sorted(states.items())),
            "genuine_forward": sum(
                item.manifest.provenance is ObservationProvenance.GENUINE_FORWARD for item in trials
            ),
            "replay": sum(
                item.manifest.provenance is ObservationProvenance.REPLAY for item in trials
            ),
        }

    def trial_detail(self, trial_id: str) -> dict[str, object]:
        trial = self.repository.get_trial(trial_id)
        performance = self.repository.performances(trial_id)
        decisions = self.repository.lifecycle_decisions(trial_id)
        observations = self.repository.observations(trial_id)
        signals = self.repository.signals(trial_id)
        fills = self.repository.fills(trial_id)
        item = self._trial_item(trial)
        item.update(
            {
                "manifest": trial.manifest.model_dump(mode="json"),
                "latest_performance": (
                    performance[-1].model_dump(mode="json") if performance else None
                ),
                "observation_count": len(observations),
                "signal_count": len(signals),
                "fill_count": len(fills),
                "lifecycle_history": [decision.model_dump(mode="json") for decision in decisions],
                "missing_evidence": self._missing_evidence(trial_id),
            }
        )
        return item

    def _missing_evidence(self, trial_id: str) -> list[str]:
        trial = self.repository.get_trial(trial_id)
        performance = self.repository.performances(trial_id)
        if not performance:
            return ["no forward observations have been evaluated"]
        latest = performance[-1]
        policy = trial.manifest.qualification_policy
        missing: list[str] = []
        if latest.elapsed_days < policy.minimum_elapsed_days:
            missing.append("minimum elapsed days")
        if latest.observations < policy.minimum_observations:
            missing.append("minimum observations")
        if latest.trades < policy.minimum_trades:
            missing.append("minimum completed trades")
        if latest.sharpe_ratio < policy.minimum_sharpe:
            missing.append("minimum Sharpe")
        if latest.excess_return < policy.minimum_excess_return:
            missing.append("benchmark-relative return")
        if latest.maximum_drawdown > policy.maximum_drawdown:
            missing.append("maximum drawdown")
        if latest.cost_resilience < policy.minimum_cost_resilience:
            missing.append("cost resilience")
        return missing

    def portfolio(self, portfolio_id: str) -> dict[str, object]:
        snapshots = self.repository.portfolio_snapshots(portfolio_id)
        state = self.repository.load_portfolio(portfolio_id)
        return {
            "portfolio_id": portfolio_id,
            "mode": "PAPER",
            "state": state.model_dump(mode="json"),
            "latest_snapshot": (snapshots[-1].model_dump(mode="json") if snapshots else None),
            "snapshot_count": len(snapshots),
            "external_order_transmission": False,
        }

    def performance(self, portfolio_id: str) -> dict[str, object]:
        trials = self.repository.list_trials(portfolio_id=portfolio_id)
        snapshots = self.repository.portfolio_snapshots(portfolio_id)
        latest_performance = {
            trial.manifest.trial_id: values[-1]
            for trial in trials
            if (values := self.repository.performances(trial.manifest.trial_id))
        }
        equity: dict[str, list[float]] = {trial.manifest.trial_id: [] for trial in trials}
        for snapshot in snapshots:
            for trial_snapshot in snapshot.trial_snapshots:
                equity.setdefault(trial_snapshot.trial_id, []).append(trial_snapshot.equity)
        latest_positions = snapshots[-1].positions if snapshots else {}
        weights: dict[str, dict[str, float]] = {trial.manifest.trial_id: {} for trial in trials}
        for value in latest_positions.values():
            trial_id = str(value["trial_id"])
            asset = value["asset"]
            if isinstance(asset, dict):
                weights[trial_id][str(asset["symbol"])] = float(value["portfolio_weight"])
        comparison = compare_champion_challengers(
            latest_performance,
            {trial.manifest.trial_id: trial.state for trial in trials},
            {key: periodic_returns(values) for key, values in equity.items()},
            weights,
        )
        payload = comparison.model_dump(mode="json")
        state = self.repository.load_portfolio(portfolio_id)
        latest_equity = snapshots[-1].equity if snapshots else state.starting_capital
        portfolio_return = latest_equity / state.starting_capital - 1.0
        benchmark_return = sum(
            trial.manifest.allocation_weight
            * latest_performance[trial.manifest.trial_id].benchmark_return
            for trial in trials
            if trial.manifest.trial_id in latest_performance
        )
        payload["portfolio_vs_benchmark"] = {
            "portfolio_return": portfolio_return,
            "frozen_weight_benchmark_return": benchmark_return,
            "excess_return": portfolio_return - benchmark_return,
        }
        payload["strategy_attribution"] = {
            trial.manifest.trial_id: (
                latest_performance[trial.manifest.trial_id].total_return
                * trial.manifest.allocated_capital
            )
            for trial in trials
            if trial.manifest.trial_id in latest_performance
        }
        return payload

    def health(self, portfolio_id: str) -> dict[str, object]:
        now = datetime.now(UTC)
        cycles = self.repository.cycles(portfolio_id)
        trials = self.repository.list_trials(portfolio_id=portfolio_id)
        last_cycle = cycles[-1] if cycles else None
        latest = max(
            (item.latest_observation_at for item in trials if item.latest_observation_at),
            default=None,
        )
        failed = sum(
            item["status"] in {ForwardCycleStatus.FAILED.value, ForwardCycleStatus.BLOCKED.value}
            for item in cycles[-20:]
        )
        successful = next(
            (
                item
                for item in reversed(cycles)
                if item["status"] == ForwardCycleStatus.COMPLETED.value
            ),
            None,
        )
        data_quality = self.repository.data_quality_events()
        return {
            "status": "degraded" if failed or self.kill_switch else "ok",
            "database": "reachable",
            "mode": "PAPER",
            "provenance_counts": dict(Counter(item.manifest.provenance.value for item in trials)),
            "state_counts": dict(Counter(item.state.value for item in trials)),
            "last_cycle": last_cycle,
            "latest_successful_cycle": successful,
            "lease": self.repository.lease_status(f"forward-cycle:{portfolio_id}"),
            "latest_observation_at": latest,
            "data_age_seconds": (now - latest).total_seconds() if latest else None,
            "recent_failed_or_blocked_cycles": failed,
            "provider": (
                {
                    "name": trials[0].manifest.data_policy.provider_name,
                    "version": trials[0].manifest.data_policy.provider_version,
                    "read_only": True,
                    "credentials_required": False,
                }
                if trials
                else None
            ),
            "missing_assets": sorted(
                {
                    asset.symbol
                    for trial in trials
                    if trial.latest_observation_at is None
                    for asset in trial.manifest.assets
                }
            ),
            "data_quality": {
                "events": len(data_quality),
                "unresolved": sum(not item.resolved for item in data_quality),
            },
            "kill_switch_engaged": self.kill_switch,
            "external_order_transmission": False,
            "qualified_forward_is_paper_only": True,
        }

    def cycles(self, portfolio_id: str) -> dict[str, object]:
        return {"items": list(self.repository.cycles(portfolio_id))}

    def data_quality(self) -> dict[str, object]:
        events = self.repository.data_quality_events()
        return {
            "items": [item.model_dump(mode="json") for item in events],
            "unresolved": sum(not item.resolved for item in events),
        }
