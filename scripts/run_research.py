"""Run a reproducible, hold-out-locked Phase 2 research batch."""

import argparse
import json
from pathlib import Path

from app.data.snapshots import DatasetSnapshotStore
from app.research import Phase2BatchResearchEngine
from scripts.phase2_common import resolve_universe, strategy_for_asset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--maximum-candidates", type=int, default=100)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    store = DatasetSnapshotStore(arguments.snapshot_root)
    manifest = store.load_manifest(arguments.dataset)
    universe = resolve_universe(arguments.universe)
    bars = {
        item.asset.symbol: store.load_bars(arguments.dataset, item.asset.symbol)
        for item in manifest.instruments
    }
    parent = strategy_for_asset(manifest.instruments[0].asset).spec
    result = Phase2BatchResearchEngine(
        maximum_candidates=arguments.maximum_candidates
    ).run_selection(
        parent,
        {"fast_window": (10, 15, 20, 25), "slow_window": (40, 60, 80)},
        bars,
        dataset_id=manifest.dataset_id,
        universe_version=universe.version_key,
        random_seed=arguments.seed,
    )
    payload = json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
