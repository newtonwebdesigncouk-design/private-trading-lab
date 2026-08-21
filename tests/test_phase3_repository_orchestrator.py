"""Restart, replay, concurrency, persistence, and operational read-model tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.database import Base, create_database_engine, session_factory
from app.forward.evidence import ForwardEvidenceStore, evidence_stream_id
from app.forward.orchestrator import ForwardCycleOrchestrator
from app.forward.portfolio import ForwardPortfolioEngine
from app.forward.read_model import ForwardReadModel
from app.forward.replay import run_deterministic_replay
from app.forward.repository import ForwardRepository
from app.models.enums import AssetClass, ForwardCycleStatus, ObservationProvenance
from app.models.market import Asset, MarketBar
from app.models.strategy import StrategySpec
from app.risk import RiskEngine
from app.strategies.base import Strategy
from scripts.phase3_common import replay_trial_manifest


class AlwaysLong(Strategy):
    def desired_exposure(self, available_history: tuple[MarketBar, ...]) -> float:
        return 1.0


def strategy(asset: Asset, start: datetime, index: int) -> AlwaysLong:
    return AlwaysLong(
        StrategySpec(
            strategy_id=f"forward-always-{index}",
            version=1,
            name=f"Always long {asset.symbol}",
            description="Deterministic orchestration fixture",
            asset_class=asset.asset_class,
            permitted_assets=(asset.symbol,),
            timeframe="1d",
            indicators=(),
            entry_conditions=("always",),
            exit_conditions=("never",),
            parameters={"strategy_type": "momentum", "lookback": 2, "threshold": 0.0},
            created_at=start,
        )
    )


def bars(asset: Asset, start: datetime, closes: tuple[float, ...]) -> tuple[MarketBar, ...]:
    return tuple(
        MarketBar(
            timestamp=start + timedelta(days=index),
            open=value,
            high=value * 1.01,
            low=value * 0.99,
            close=value,
            adjusted_close=value,
            volume=10_000,
            asset=asset,
            source="frozen-replay-fixture",
            interval="1d",
        )
        for index, value in enumerate(closes)
    )


def test_replay_cycles_are_multi_trial_restart_safe_and_idempotent(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'forward.db'}")
    Base.metadata.create_all(engine)
    repository = ForwardRepository(session_factory(engine))
    start = datetime(2024, 1, 3, tzinfo=UTC)
    assets = (
        Asset(symbol="AAA", asset_class=AssetClass.EQUITY, exchange="TEST"),
        Asset(symbol="BBB", asset_class=AssetClass.ETF, exchange="TEST"),
    )
    implementations = [strategy(asset, start, index) for index, asset in enumerate(assets)]
    manifests = [
        replay_trial_manifest(
            portfolio_id="replay-portfolio",
            strategy=implementation,
            asset=asset,
            start=start,
            code_revision="test",
            source_dataset_id="snapshot-v1",
        )
        for asset, implementation in zip(assets, implementations, strict=True)
    ]
    trials = tuple(repository.create_trial(item) for item in manifests)
    strategies = {
        item.manifest.trial_id: implementation
        for item, implementation in zip(trials, implementations, strict=True)
    }
    all_bars = {
        asset.symbol: bars(asset, start - timedelta(days=2), (98, 99, 100, 101, 102, 103))
        for asset in assets
    }
    evidence_store = ForwardEvidenceStore(tmp_path / "evidence")
    stream = evidence_stream_id(
        "replay-portfolio",
        ObservationProvenance.REPLAY,
        assets,
        manifests[0].data_policy,
    )
    orchestrator = ForwardCycleOrchestrator(
        repository,
        ForwardPortfolioEngine(RiskEngine(manifests[0].risk_policy.limits)),
    )
    results = run_deterministic_replay(
        repository=repository,
        orchestrator=orchestrator,
        evidence_store=evidence_store,
        stream_id=stream,
        source_dataset_id="snapshot-v1",
        trials=trials,
        strategies=strategies,
        bars_by_symbol=all_bars,
        start=start,
        end=start + timedelta(days=3),
        code_revision="test",
    )
    assert results[-1].status is ForwardCycleStatus.DUPLICATE
    assert not results[-1].processed
    assert any(result.orders for result in results[:-1])
    assert any(result.fills for result in results[:-1])
    assert all(result.provenance is ObservationProvenance.REPLAY for result in results)
    cycles = repository.cycles("replay-portfolio")
    assert len(cycles) == 4
    assert cycles[0]["retry_count"] == 1
    assert all(item["status"] == ForwardCycleStatus.COMPLETED.value for item in cycles)
    restored = repository.load_portfolio("replay-portfolio")
    assert restored.reserve_cash >= 0
    assert all(ledger.cash >= 0 for ledger in restored.ledgers.values())
    assert set(restored.ledgers) == {item.manifest.trial_id for item in trials}
    assert all(
        observation.bar.timestamp >= start
        for trial in trials
        for observation in repository.observations(trial.manifest.trial_id)
    )

    read_model = ForwardReadModel(repository, kill_switch=False)
    trial_view = read_model.trials()
    assert trial_view["replay"] == 2
    assert trial_view["genuine_forward"] == 0
    assert read_model.portfolio("replay-portfolio")["external_order_transmission"] is False
    assert read_model.performance("replay-portfolio")["qualification_note"]
    assert read_model.health("replay-portfolio")["database"] == "reachable"


def test_leases_data_quality_blocks_and_provenance_mixing_fail_closed(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'blocks.db'}")
    Base.metadata.create_all(engine)
    repository = ForwardRepository(session_factory(engine))
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    asset = Asset(symbol="AAA", asset_class=AssetClass.EQUITY, exchange="TEST")
    implementation = strategy(asset, timestamp, 1)
    manifest = replay_trial_manifest(
        portfolio_id="blocked-portfolio",
        strategy=implementation,
        asset=asset,
        start=timestamp,
        code_revision="test",
        source_dataset_id="snapshot-v1",
    )
    trial = repository.create_trial(manifest)
    assert repository.acquire_lease(
        "forward-cycle:blocked-portfolio",
        "owner-one",
        now=timestamp,
        ttl=timedelta(minutes=5),
    )
    assert not repository.acquire_lease(
        "forward-cycle:blocked-portfolio",
        "owner-two",
        now=timestamp + timedelta(minutes=1),
        ttl=timedelta(minutes=5),
    )
    blocked = repository.record_data_quality_block(
        portfolio_id="blocked-portfolio",
        trials=(trial,),
        provenance=ObservationProvenance.REPLAY,
        timestamp=timestamp,
        lease_owner="owner-one",
        detail="partial provider response",
    )
    assert blocked.status is ForwardCycleStatus.BLOCKED
    assert not blocked.orders and not blocked.fills
    assert repository.get_trial(manifest.trial_id).state.value == "PAUSED_DATA_QUALITY"
    assert repository.data_quality_events()[0].detail == "partial provider response"
    duplicate = repository.record_data_quality_block(
        portfolio_id="blocked-portfolio",
        trials=(trial,),
        provenance=ObservationProvenance.REPLAY,
        timestamp=timestamp,
        lease_owner="owner-one",
        detail="partial provider response",
    )
    assert duplicate.status is ForwardCycleStatus.DUPLICATE

    orchestrator = ForwardCycleOrchestrator(
        repository, ForwardPortfolioEngine(RiskEngine(manifest.risk_policy.limits))
    )
    orchestrator.ensure_portfolio((repository.get_trial(manifest.trial_id),))
    evidence_store = ForwardEvidenceStore(tmp_path / "mix")
    from app.forward.evidence import append_replay_evidence

    evidence = append_replay_evidence(
        evidence_store,
        stream_id="forward-stream-mix",
        source_dataset_id="snapshot-v1",
        bars_by_symbol={asset.symbol: (bars(asset, timestamp, (100,))[0],)},
        timestamp=timestamp,
        code_revision="test",
    ).manifest
    assert evidence is not None
    repository.save_evidence_manifest(evidence)
    genuine = evidence.model_copy(update={"provenance": ObservationProvenance.GENUINE_FORWARD})
    with pytest.raises(ValueError, match="provenance"):
        orchestrator.process_timestamp(
            evidence=genuine,
            trials=(repository.get_trial(manifest.trial_id),),
            strategies={manifest.trial_id: implementation},
            current_bars={asset.symbol: bars(asset, timestamp, (100,))[0]},
            histories={asset.symbol: bars(asset, timestamp, (100,))},
            timestamp=timestamp,
            evaluation_timestamp=timestamp,
            lease_owner="test",
            allow_new_orders=True,
        )
    recovered = orchestrator.process_timestamp(
        evidence=evidence,
        trials=(repository.get_trial(manifest.trial_id),),
        strategies={manifest.trial_id: implementation},
        current_bars={asset.symbol: bars(asset, timestamp, (100,))[0]},
        histories={asset.symbol: bars(asset, timestamp, (100,))},
        timestamp=timestamp,
        evaluation_timestamp=timestamp,
        lease_owner="test",
        allow_new_orders=True,
    )
    assert recovered.status is ForwardCycleStatus.COMPLETED
    assert repository.unresolved_data_quality_count(manifest.trial_id) == 0
    assert repository.data_quality_events()[0].resolved
