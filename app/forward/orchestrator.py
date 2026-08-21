"""Restart-safe orchestration for genuine and replay forward PAPER observations."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from app.forward.analytics import calculate_drift_diagnostic, calculate_forward_performance
from app.forward.evidence import ForwardDataQualityError, IncrementalMarketDataCollector
from app.forward.lifecycle import evaluate_forward_lifecycle
from app.forward.models import (
    ForwardCycleResult,
    ForwardEvidenceManifest,
    ForwardObservation,
    ForwardPortfolioState,
    ForwardTrial,
    canonical_hash,
)
from app.forward.portfolio import ForwardPortfolioEngine
from app.forward.repository import ForwardRepository
from app.models.enums import ForwardCycleStatus, ObservationProvenance
from app.models.market import MarketBar
from app.strategies.base import Strategy
from app.validation.regimes import classify_regimes


def forward_cycle_id(
    portfolio_id: str,
    evidence_manifest_id: str,
    timestamp: datetime,
    provenance: ObservationProvenance,
) -> str:
    identity = {
        "portfolio_id": portfolio_id,
        "evidence_manifest_id": evidence_manifest_id,
        "timestamp": timestamp.isoformat(),
        "provenance": provenance.value,
    }
    return f"forward-cycle-{canonical_hash(identity)[:24]}"


def _regime_for_prefix(history: Sequence[MarketBar]) -> str | None:
    """The final label is calculated from data available at the current bar only."""
    observations = classify_regimes(history)
    return observations[-1].label if observations else None


class ForwardCycleOrchestrator:
    """Coordinates evidence, PAPER accounting, analytics, and atomic persistence."""

    def __init__(
        self,
        repository: ForwardRepository,
        portfolio_engine: ForwardPortfolioEngine,
    ) -> None:
        self.repository = repository
        self.portfolio_engine = portfolio_engine

    def ensure_portfolio(self, trials: Sequence[ForwardTrial]) -> ForwardPortfolioState:
        manifests = tuple(item.manifest for item in trials)
        initial = self.portfolio_engine.initial_state(manifests)
        return self.repository.ensure_portfolio(initial, manifests)

    def process_timestamp(
        self,
        *,
        evidence: ForwardEvidenceManifest,
        trials: Sequence[ForwardTrial],
        strategies: Mapping[str, Strategy],
        current_bars: Mapping[str, MarketBar],
        histories: Mapping[str, Sequence[MarketBar]],
        timestamp: datetime,
        evaluation_timestamp: datetime,
        lease_owner: str,
        allow_new_orders: bool,
        advance_paper_portfolio: bool = True,
    ) -> ForwardCycleResult:
        if not trials:
            raise ValueError("forward processing requires at least one trial")
        if timestamp.tzinfo is None or evaluation_timestamp.tzinfo is None:
            raise ValueError("forward timestamps must be timezone-aware")
        portfolio_id = trials[0].manifest.portfolio_id
        provenance = trials[0].manifest.provenance
        if evidence.provenance is not provenance:
            raise ValueError("evidence and trial provenance cannot mix")
        if any(
            item.manifest.portfolio_id != portfolio_id or item.manifest.provenance is not provenance
            for item in trials
        ):
            raise ValueError("all concurrent trials must share portfolio and provenance")
        if set(strategies) != {item.manifest.trial_id for item in trials}:
            raise ValueError("a frozen strategy implementation is required for every trial")
        for symbol, history in histories.items():
            if any(bar.timestamp > timestamp for bar in history):
                raise ValueError(f"look-ahead bar supplied for {symbol}")
        if any(bar.timestamp != timestamp for bar in current_bars.values()):
            raise ValueError("current bars must match the cycle timestamp")

        cycle_id = forward_cycle_id(portfolio_id, evidence.manifest_id, timestamp, provenance)
        begun = self.repository.begin_cycle(
            cycle_id=cycle_id,
            portfolio_id=portfolio_id,
            evidence_manifest_id=evidence.manifest_id,
            provenance=provenance,
            market_timestamp=timestamp,
            lease_owner=lease_owner,
        )
        if not begun:
            return ForwardCycleResult(
                cycle_id=cycle_id,
                portfolio_id=portfolio_id,
                evidence_manifest_id=evidence.manifest_id,
                provenance=provenance,
                status=ForwardCycleStatus.DUPLICATE,
                processed=False,
                timestamp=timestamp,
            )

        try:
            refreshed_trials = {
                item.manifest.trial_id: self.repository.get_trial(item.manifest.trial_id)
                for item in trials
            }
            state = self.repository.load_portfolio(portfolio_id)
            prior_portfolio_snapshots = self.repository.portfolio_snapshots(portfolio_id)
            step = self.portfolio_engine.step(
                state,
                refreshed_trials,
                strategies,
                current_bars if advance_paper_portfolio else {},
                histories,
                cycle_id=cycle_id,
                timestamp=timestamp,
                evaluation_timestamp=evaluation_timestamp,
                provenance=provenance,
                allow_new_orders=allow_new_orders,
                prior_snapshots=prior_portfolio_snapshots,
            )

            regime_by_symbol = {
                symbol: _regime_for_prefix(history) for symbol, history in histories.items()
            }
            observations: list[ForwardObservation] = []
            for trial in refreshed_trials.values():
                manifest = trial.manifest
                for asset in manifest.assets:
                    bar = current_bars.get(asset.symbol)
                    if bar is None or bar.timestamp < manifest.start_timestamp:
                        continue
                    identity = {
                        "trial_id": manifest.trial_id,
                        "manifest_id": evidence.manifest_id,
                        "symbol": asset.symbol,
                        "timestamp": bar.timestamp.isoformat(),
                        "provenance": provenance.value,
                    }
                    observations.append(
                        ForwardObservation(
                            observation_id=("forward-observation-" + canonical_hash(identity)[:24]),
                            trial_id=manifest.trial_id,
                            cycle_id=cycle_id,
                            evidence_manifest_id=evidence.manifest_id,
                            provenance=provenance,
                            bar=bar,
                            available_at=evaluation_timestamp,
                            regime=regime_by_symbol.get(asset.symbol),
                        )
                    )
            signals = tuple(
                signal.model_copy(
                    update={
                        "regime": regime_by_symbol.get(
                            refreshed_trials[signal.trial_id].manifest.assets[0].symbol
                        )
                    }
                )
                for signal in step.signals
            )

            prior_trial_snapshots = [
                trial_snapshot
                for snapshot in prior_portfolio_snapshots
                for trial_snapshot in snapshot.trial_snapshots
            ]
            all_trial_snapshots = [*prior_trial_snapshots, *step.snapshot.trial_snapshots]
            performance = {}
            diagnostics = []
            decisions = []
            for trial_id, trial in refreshed_trials.items():
                prior_observations = self.repository.observations(trial_id)
                prior_signals = self.repository.signals(trial_id)
                prior_fills = self.repository.fills(trial_id)
                ledger = step.state.ledgers[trial_id]
                item = calculate_forward_performance(
                    trial.manifest,
                    all_trial_snapshots,
                    (*prior_observations, *observations),
                    (*prior_signals, *signals),
                    (*prior_fills, *step.fills),
                    trade_pnl=tuple(trade.net_pnl for trade in ledger.trades),
                )
                performance[trial_id] = item
                diagnostic = calculate_drift_diagnostic(
                    trial.manifest,
                    item,
                    all_trial_snapshots,
                    data_age_seconds=(evaluation_timestamp - timestamp).total_seconds(),
                )
                diagnostics.append(diagnostic)
                decisions.append(
                    evaluate_forward_lifecycle(
                        trial,
                        item,
                        diagnostic,
                        cycle_id=cycle_id,
                        timestamp=timestamp,
                        unresolved_data_quality_failures=0,
                        risk_breaches=len(step.risk_rejections.get(trial_id, ())),
                    )
                )

            result = ForwardCycleResult(
                cycle_id=cycle_id,
                portfolio_id=portfolio_id,
                evidence_manifest_id=evidence.manifest_id,
                provenance=provenance,
                status=ForwardCycleStatus.COMPLETED,
                processed=True,
                timestamp=timestamp,
                observations=tuple(observations),
                signals=signals,
                orders=step.orders,
                fills=step.fills,
                snapshot=step.snapshot,
                lifecycle_decisions=tuple(decisions),
                degradation=tuple(diagnostics),
                risk_rejections=step.risk_rejections,
            )
            self.repository.complete_cycle(result, step.state, performance)
            return result
        except BaseException as exc:
            self.repository.fail_cycle(cycle_id, f"{type(exc).__name__}: {exc}")
            raise

    def run_current_update(
        self,
        *,
        collector: IncrementalMarketDataCollector,
        stream_id: str,
        trials: Sequence[ForwardTrial],
        strategies: Mapping[str, Strategy],
        warmup_histories: Mapping[str, Sequence[MarketBar]],
        as_of: datetime,
        lease_owner: str,
        lease_ttl: timedelta = timedelta(minutes=15),
    ) -> tuple[ForwardCycleResult, ...]:
        """Collect current GET-only data and process each unseen timestamp once."""
        if not trials:
            return ()
        portfolio_id = trials[0].manifest.portfolio_id
        if any(
            item.manifest.provenance is not ObservationProvenance.GENUINE_FORWARD for item in trials
        ):
            raise ValueError("current provider updates require genuine-forward trials")
        lease_key = f"forward-cycle:{portfolio_id}"
        if not self.repository.acquire_lease(lease_key, lease_owner, now=as_of, ttl=lease_ttl):
            return ()
        try:
            policy = trials[0].manifest.data_policy
            if any(item.manifest.data_policy != policy for item in trials):
                raise ValueError("concurrent current-data trials must share a data policy")
            assets = tuple(
                sorted(
                    {
                        asset.cache_key: asset
                        for trial in trials
                        for asset in trial.manifest.assets
                    }.values(),
                    key=lambda item: item.cache_key,
                )
            )
            forward_start = min(item.manifest.start_timestamp for item in trials)
            try:
                evidence_result = collector.collect(
                    stream_id=stream_id,
                    assets=assets,
                    forward_start=forward_start,
                    as_of=as_of,
                    data_policy=policy,
                )
            except ForwardDataQualityError as exc:
                return (
                    self.repository.record_data_quality_block(
                        portfolio_id=portfolio_id,
                        trials=trials,
                        provenance=ObservationProvenance.GENUINE_FORWARD,
                        timestamp=as_of,
                        lease_owner=lease_owner,
                        detail=str(exc),
                    ),
                )
            manifest = evidence_result.manifest
            if manifest is None or not evidence_result.new_bars:
                return ()
            self.repository.save_evidence_manifest(manifest)
            timestamps = sorted(
                {bar.timestamp for bars in evidence_result.new_bars.values() for bar in bars}
            )
            complete_evidence = collector.store.load_all_bars(stream_id)
            results: list[ForwardCycleResult] = []
            for timestamp in timestamps:
                current: dict[str, MarketBar] = {}
                for symbol, bars in evidence_result.new_bars.items():
                    for bar in bars:
                        if bar.timestamp == timestamp:
                            current[symbol] = bar
                histories = {
                    symbol: tuple(
                        [
                            *(
                                bar
                                for bar in warmup_histories.get(symbol, ())
                                if bar.timestamp < forward_start
                            ),
                            *(
                                bar
                                for bar in complete_evidence.get(symbol, ())
                                if bar.timestamp <= timestamp
                            ),
                        ]
                    )
                    for symbol in {**warmup_histories, **complete_evidence}
                }
                results.append(
                    self.process_timestamp(
                        evidence=manifest,
                        trials=trials,
                        strategies=strategies,
                        current_bars=current,
                        histories=histories,
                        timestamp=timestamp,
                        evaluation_timestamp=as_of,
                        lease_owner=lease_owner,
                        allow_new_orders=timestamp == timestamps[-1],
                        advance_paper_portfolio=timestamp == timestamps[-1],
                    )
                )
            return tuple(results)
        finally:
            self.repository.release_lease(lease_key, lease_owner, now=datetime.now(UTC))
