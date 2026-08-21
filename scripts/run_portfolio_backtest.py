"""Run a bounded multi-asset portfolio backtest from a frozen snapshot."""

import argparse
import json
from pathlib import Path

from app.data.snapshots import DatasetSnapshotStore
from app.portfolio import PortfolioBacktestEngine
from scripts.phase2_common import resolve_universe, strategy_for_asset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    store = DatasetSnapshotStore(arguments.snapshot_root)
    manifest = store.load_manifest(arguments.dataset)
    universe = resolve_universe(arguments.universe)
    bars = {
        item.asset.symbol: store.load_bars(arguments.dataset, item.asset.symbol)
        for item in manifest.instruments
    }
    strategies = {
        item.asset.symbol: strategy_for_asset(item.asset) for item in manifest.instruments
    }
    result = PortfolioBacktestEngine().run(
        strategies,
        bars,
        dataset_id=manifest.dataset_id,
        universe=universe,
        adjustment_policy=manifest.adjustment_policy,
    )
    payload = json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
