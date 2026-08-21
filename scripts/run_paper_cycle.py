"""Perform exactly one persistent local paper-simulation cycle."""

import argparse
import json
from datetime import timedelta
from pathlib import Path

from app.data.snapshots import DatasetSnapshotStore
from app.database import Base, create_database_engine, session_factory
from app.paper_trading import PersistentPaperLab, PersistentPaperRepository
from app.risk import RiskEngine, RiskLimits
from scripts.phase2_common import strategy_for_asset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--database-url", default="sqlite:///./data/trading_lab.db")
    parser.add_argument("--starting-cash", type=float, default=100_000)
    arguments = parser.parse_args()
    store = DatasetSnapshotStore(arguments.snapshot_root)
    manifest = store.load_manifest(arguments.dataset)
    bars = {
        item.asset.symbol: store.load_bars(arguments.dataset, item.asset.symbol)
        for item in manifest.instruments
    }
    strategies = {
        item.asset.symbol: strategy_for_asset(item.asset) for item in manifest.instruments
    }
    database_engine = create_database_engine(arguments.database_url)
    Base.metadata.create_all(database_engine)
    repository = PersistentPaperRepository(session_factory(database_engine))
    try:
        repository.load_account(arguments.account)
    except KeyError:
        repository.create_account(arguments.account, starting_cash=arguments.starting_cash)
    risk = RiskEngine(RiskLimits(stale_after=timedelta(hours=36)))
    result = PersistentPaperLab(repository, risk).run_cycle(
        arguments.account,
        arguments.dataset,
        strategies,
        bars,
        evaluation_timestamp=manifest.actual_end,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
