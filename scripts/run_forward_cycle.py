"""Run one scheduler-neutral, GET-only current-data Phase 3 PAPER cycle."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.data.providers import YahooReadOnlyProvider
from app.data.snapshots import DatasetSnapshotStore
from app.database import create_database_engine, session_factory
from app.forward.evidence import (
    ForwardEvidenceStore,
    IncrementalMarketDataCollector,
    evidence_stream_id,
)
from app.forward.orchestrator import ForwardCycleOrchestrator
from app.forward.portfolio import ForwardPortfolioEngine
from app.forward.repository import ForwardRepository
from app.models.enums import ObservationProvenance
from app.risk import RiskEngine
from app.strategies.reference import strategy_from_spec
from scripts.phase3_common import revision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portfolio", required=True)
    parser.add_argument("--database-url", default="sqlite:///./data/trading_lab.db")
    parser.add_argument("--evidence-root", type=Path, default=Path("data/forward_evidence"))
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--owner", default="phase3-owner-cycle")
    arguments = parser.parse_args()
    as_of = (
        datetime.fromisoformat(arguments.as_of.replace("Z", "+00:00"))
        if arguments.as_of
        else datetime.now(UTC)
    )
    repository = ForwardRepository(session_factory(create_database_engine(arguments.database_url)))
    trials = repository.list_trials(
        provenance=ObservationProvenance.GENUINE_FORWARD,
        portfolio_id=arguments.portfolio,
    )
    if not trials:
        raise ValueError("no genuine-forward trial exists for this portfolio")
    data_policy = trials[0].manifest.data_policy
    warmup_id = data_policy.warmup_dataset_id
    if warmup_id is None:
        raise ValueError("genuine forward trials require a frozen warm-up dataset")
    snapshot_store = DatasetSnapshotStore(arguments.snapshot_root)
    warmup_manifest = snapshot_store.load_manifest(warmup_id)
    warmup = {
        item.asset.symbol: snapshot_store.load_bars(warmup_id, item.asset.symbol)
        for item in warmup_manifest.instruments
    }
    provider_assets = {
        asset: ("BTC-USD" if asset.symbol == "BTCUSD" else asset.symbol)
        for trial in trials
        for asset in trial.manifest.assets
    }
    provider = YahooReadOnlyProvider(provider_assets)
    evidence_store = ForwardEvidenceStore(arguments.evidence_root)
    collector = IncrementalMarketDataCollector(provider, evidence_store, code_revision=revision())
    risk = RiskEngine(trials[0].manifest.risk_policy.limits)
    orchestrator = ForwardCycleOrchestrator(repository, ForwardPortfolioEngine(risk))
    orchestrator.ensure_portfolio(trials)
    assets = tuple(provider_assets)
    stream_id = evidence_stream_id(
        arguments.portfolio,
        ObservationProvenance.GENUINE_FORWARD,
        assets,
        data_policy,
    )
    results = orchestrator.run_current_update(
        collector=collector,
        stream_id=stream_id,
        trials=trials,
        strategies={
            item.manifest.trial_id: strategy_from_spec(item.manifest.strategy) for item in trials
        },
        warmup_histories=warmup,
        as_of=as_of,
        lease_owner=arguments.owner,
        lease_ttl=timedelta(minutes=15),
    )
    print(
        json.dumps(
            {
                "portfolio_id": arguments.portfolio,
                "cycles": [item.model_dump(mode="json") for item in results],
                "provider": provider.provider_metadata().model_dump(mode="json"),
                "mode": "PAPER",
                "external_order_transmission": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
