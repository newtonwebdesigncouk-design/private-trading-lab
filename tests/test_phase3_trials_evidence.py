"""Frozen trial identity, evidence lineage, current data, and provenance tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.backtesting.models import CostAssumptions
from app.data.synthetic import SyntheticMarketDataProvider
from app.forward.evidence import (
    ForwardDataQualityError,
    ForwardEvidenceStore,
    IncrementalMarketDataCollector,
    append_replay_evidence,
    evidence_stream_id,
)
from app.forward.models import (
    ForwardBaselineProfile,
    ForwardBenchmarkDefinition,
    ForwardDataPolicy,
    ForwardDegradationPolicy,
    ForwardQualificationPolicy,
    ForwardRiskPolicy,
    ForwardTrialManifest,
)
from app.models.enums import AssetClass, ObservationProvenance
from app.models.market import Asset, MarketBar
from app.models.strategy import StrategySpec
from app.risk import RiskLimits


def trial_manifest(
    asset: Asset,
    *,
    provenance: ObservationProvenance = ObservationProvenance.REPLAY,
    start: datetime | None = None,
    allocation_weight: float = 0.30,
) -> ForwardTrialManifest:
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    strategy = StrategySpec(
        strategy_id=f"forward-{asset.symbol.lower()}",
        version=2,
        name="Frozen forward fixture",
        description="Test-only deterministic strategy specification",
        asset_class=asset.asset_class,
        permitted_assets=(asset.symbol,),
        timeframe="1d",
        indicators=(),
        entry_conditions=("always",),
        exit_conditions=("never",),
        parameters={"strategy_type": "momentum", "lookback": 2, "threshold": 0.0},
        created_at=start,
    )
    return ForwardTrialManifest.create(
        portfolio_id=f"portfolio-{provenance.value.lower()}",
        strategy=strategy,
        assets=(asset,),
        universe_version="frozen-universe-v1",
        benchmark=ForwardBenchmarkDefinition(
            benchmark_id=f"{asset.symbol}-benchmark-v1", symbols=(asset.symbol,)
        ),
        portfolio_starting_capital=10_000,
        allocation_weight=allocation_weight,
        costs=CostAssumptions(),
        risk_policy=ForwardRiskPolicy(
            limits=RiskLimits(stale_after=timedelta(days=2)),
            maximum_strategy_allocation=0.40,
        ),
        data_policy=ForwardDataPolicy(
            provider_name="immutable-historical-replay",
            provider_version="phase3-replay-v1",
            adjustment_policy="TOTAL_RETURN_ADJUSTED",
            corporate_action_policy="frozen",
            warmup_dataset_id="warmup-v1",
        ),
        start_timestamp=start,
        qualification_policy=ForwardQualificationPolicy(
            minimum_elapsed_days=2,
            minimum_observations=2,
            minimum_trades=0,
            minimum_sharpe=-100,
            minimum_excess_return=-100,
            minimum_cost_resilience=0,
        ),
        degradation_policy=ForwardDegradationPolicy(rolling_window=5, minimum_observations=5),
        baseline_profile=ForwardBaselineProfile(),
        code_revision="test-revision",
        provenance=provenance,
        created_at=start,
    )


def bar(asset: Asset, timestamp: datetime, close: float = 100) -> MarketBar:
    return MarketBar(
        timestamp=timestamp,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adjusted_close=close,
        volume=1_000,
        asset=asset,
        source="phase3-test",
        interval="1d",
    )


def test_material_trial_changes_require_a_new_identity() -> None:
    asset = Asset(symbol="TEST", asset_class=AssetClass.EQUITY, exchange="TEST")
    manifest = trial_manifest(asset)
    assert manifest.trial_id.startswith("forward-")
    assert manifest.configuration_fingerprint
    changed = manifest.model_dump(mode="json")
    changed["allocation_weight"] = 0.20
    with pytest.raises(ValidationError, match="fingerprint mismatch"):
        ForwardTrialManifest.model_validate(changed)
    new = trial_manifest(asset, allocation_weight=0.20)
    assert new.trial_id != manifest.trial_id


def test_evidence_is_append_only_chained_idempotent_and_checksum_verified(
    tmp_path: Path,
) -> None:
    asset = Asset(symbol="TEST", asset_class=AssetClass.EQUITY, exchange="TEST")
    store = ForwardEvidenceStore(tmp_path / "evidence")
    stream = "forward-stream-test"
    first_time = datetime(2024, 1, 1, tzinfo=UTC)
    first = append_replay_evidence(
        store,
        stream_id=stream,
        source_dataset_id="snapshot-v1",
        bars_by_symbol={asset.symbol: (bar(asset, first_time),)},
        timestamp=first_time,
        code_revision="test",
    )
    assert first.created and first.manifest is not None
    duplicate = append_replay_evidence(
        store,
        stream_id=stream,
        source_dataset_id="snapshot-v1",
        bars_by_symbol={asset.symbol: (bar(asset, first_time),)},
        timestamp=first_time,
        code_revision="test",
    )
    assert not duplicate.created
    second_time = first_time + timedelta(days=1)
    second = append_replay_evidence(
        store,
        stream_id=stream,
        source_dataset_id="snapshot-v1",
        bars_by_symbol={asset.symbol: (bar(asset, second_time, 101),)},
        timestamp=second_time,
        code_revision="test",
    )
    assert second.manifest is not None
    assert second.manifest.previous_manifest_id == first.manifest.manifest_id
    assert len(store.load_all_bars(stream)[asset.symbol]) == 2
    directory = next(
        item
        for item in (tmp_path / "evidence" / stream).iterdir()
        if item.name.endswith(first.manifest.manifest_id)
    )
    artifact = directory / first.manifest.instruments[0].artifact
    artifact.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ForwardDataQualityError, match="checksum"):
        store.load_manifest_bars(stream, first.manifest.manifest_id)


def test_current_collector_is_read_only_incremental_and_fails_closed_when_stale(
    tmp_path: Path,
) -> None:
    provider = SyntheticMarketDataProvider(seed=11)
    asset = next(
        item
        for item in provider.supported_assets()
        if item.asset_class is AssetClass.CRYPTOCURRENCY
    )
    metadata = provider.provider_metadata()
    start = datetime(2024, 1, 1, 21, tzinfo=UTC)
    as_of = datetime(2024, 1, 3, 21, tzinfo=UTC)
    policy = ForwardDataPolicy(
        provider_name=metadata.name,
        provider_version=metadata.version,
        adjustment_policy="SYNTHETIC",
        corporate_action_policy="synthetic",
        maximum_staleness=timedelta(days=2),
    )
    store = ForwardEvidenceStore(tmp_path / "current")
    stream = evidence_stream_id(
        "portfolio-current", ObservationProvenance.GENUINE_FORWARD, (asset,), policy
    )
    collector = IncrementalMarketDataCollector(provider, store, code_revision="test")
    collected = collector.collect(
        stream_id=stream,
        assets=(asset,),
        forward_start=start,
        as_of=as_of,
        data_policy=policy,
    )
    assert collected.created and collected.manifest is not None
    assert collected.manifest.provenance is ObservationProvenance.GENUINE_FORWARD
    assert collected.manifest.source_dataset_id is None
    repeated = collector.collect(
        stream_id=stream,
        assets=(asset,),
        forward_start=start,
        as_of=as_of,
        data_policy=policy,
    )
    assert not repeated.created and repeated.new_bars == {}

    stale_policy = policy.model_copy(update={"maximum_staleness": timedelta(hours=1)})
    stale_stream = evidence_stream_id(
        "portfolio-stale", ObservationProvenance.GENUINE_FORWARD, (asset,), stale_policy
    )
    with pytest.raises(ForwardDataQualityError, match="stale"):
        collector.collect(
            stream_id=stale_stream,
            assets=(asset,),
            forward_start=start,
            as_of=datetime(2024, 1, 3, 9, tzinfo=UTC),
            data_policy=stale_policy,
        )
