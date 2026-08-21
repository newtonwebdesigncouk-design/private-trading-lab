"""Deterministic engineering replay using the genuine forward cycle machinery."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from app.forward.evidence import ForwardEvidenceStore, append_replay_evidence
from app.forward.models import ForwardCycleResult, ForwardEvidenceManifest, ForwardTrial
from app.forward.orchestrator import ForwardCycleOrchestrator, forward_cycle_id
from app.forward.repository import ForwardRepository
from app.models.enums import ForwardCycleStatus, ObservationProvenance
from app.models.market import MarketBar
from app.strategies.base import Strategy


def run_deterministic_replay(
    *,
    repository: ForwardRepository,
    orchestrator: ForwardCycleOrchestrator,
    evidence_store: ForwardEvidenceStore,
    stream_id: str,
    source_dataset_id: str,
    trials: Sequence[ForwardTrial],
    strategies: Mapping[str, Strategy],
    bars_by_symbol: Mapping[str, Sequence[MarketBar]],
    start: datetime,
    end: datetime,
    code_revision: str,
    lease_owner: str = "phase3-replay",
    verify_recovery: bool = True,
) -> tuple[ForwardCycleResult, ...]:
    """Reveal frozen bars one timestamp at a time, always labelled ``REPLAY``."""
    if any(item.manifest.provenance is not ObservationProvenance.REPLAY for item in trials):
        raise ValueError("replay harness accepts REPLAY trials only")
    orchestrator.ensure_portfolio(trials)
    timestamps = sorted(
        {
            bar.timestamp
            for bars in bars_by_symbol.values()
            for bar in bars
            if start <= bar.timestamp <= end
        }
    )
    histories: dict[str, list[MarketBar]] = {
        symbol: [bar for bar in bars if bar.timestamp < start]
        for symbol, bars in bars_by_symbol.items()
    }
    results: list[ForwardCycleResult] = []
    recovery_injected = False
    for timestamp in timestamps:
        current = {
            symbol: bar
            for symbol, bars in bars_by_symbol.items()
            for bar in bars
            if bar.timestamp == timestamp
        }
        for symbol, bar in current.items():
            histories.setdefault(symbol, []).append(bar)
        evidence_result = append_replay_evidence(
            evidence_store,
            stream_id=stream_id,
            source_dataset_id=source_dataset_id,
            bars_by_symbol={key: (value,) for key, value in current.items()},
            timestamp=timestamp,
            code_revision=code_revision,
        )
        manifest = evidence_result.manifest
        if manifest is None:
            raise RuntimeError("replay evidence manifest was not created")
        repository.save_evidence_manifest(manifest)
        if verify_recovery and not recovery_injected:
            cycle_id = forward_cycle_id(
                trials[0].manifest.portfolio_id,
                manifest.manifest_id,
                timestamp,
                ObservationProvenance.REPLAY,
            )
            repository.begin_cycle(
                cycle_id=cycle_id,
                portfolio_id=trials[0].manifest.portfolio_id,
                evidence_manifest_id=manifest.manifest_id,
                provenance=ObservationProvenance.REPLAY,
                market_timestamp=timestamp,
                lease_owner=lease_owner,
            )
            repository.fail_cycle(cycle_id, "intentional replay recovery probe")
            recovery_injected = True
        results.append(
            orchestrator.process_timestamp(
                evidence=manifest,
                trials=trials,
                strategies=strategies,
                current_bars=current,
                histories={key: tuple(value) for key, value in histories.items()},
                timestamp=timestamp,
                evaluation_timestamp=timestamp,
                lease_owner=lease_owner,
                allow_new_orders=True,
            )
        )
    if results:
        final = results[-1]
        duplicate = orchestrator.process_timestamp(
            evidence=repository_evidence_manifest(evidence_store, stream_id, final),
            trials=trials,
            strategies=strategies,
            current_bars={
                symbol: values[-1]
                for symbol, values in histories.items()
                if values and values[-1].timestamp == final.timestamp
            },
            histories={key: tuple(value) for key, value in histories.items()},
            timestamp=final.timestamp,
            evaluation_timestamp=final.timestamp,
            lease_owner=lease_owner,
            allow_new_orders=True,
        )
        if duplicate.status is not ForwardCycleStatus.DUPLICATE or duplicate.processed:
            raise RuntimeError("replay idempotency verification failed")
        results.append(duplicate)
    return tuple(results)


def repository_evidence_manifest(
    store: ForwardEvidenceStore,
    stream_id: str,
    result: ForwardCycleResult,
) -> ForwardEvidenceManifest:
    """Locate the immutable manifest referenced by a replay result."""
    return next(
        item
        for item in store.list_manifests(stream_id)
        if item.manifest_id == result.evidence_manifest_id
    )
