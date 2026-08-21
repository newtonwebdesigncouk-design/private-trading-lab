"""Ingest public read-only history and freeze an immutable dataset snapshot."""

import argparse
import json
import subprocess
from pathlib import Path

from app.data.providers import YahooReadOnlyProvider
from app.data.snapshots import DatasetIngestor, DatasetSnapshotStore
from scripts.phase2_common import configured_assets, load_json, parse_timestamp


def _revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, check=False, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    arguments = parser.parse_args()
    config = load_json(arguments.config)
    assets = configured_assets(config)
    provider = YahooReadOnlyProvider(
        assets,
        maximum_attempts=int(config.get("maximum_attempts", 3)),
        timeout_seconds=float(config.get("timeout_seconds", 20)),
    )
    store = DatasetSnapshotStore(Path(str(config.get("snapshot_root", "data/snapshots"))))
    manifest = DatasetIngestor(store).ingest(
        provider,
        tuple(assets),
        parse_timestamp(str(config["start"])),
        parse_timestamp(str(config["end"])),
        interval=str(config.get("interval", "1d")),
        dataset_name=str(config["dataset_name"]),
        code_revision=_revision(),
        corporate_action_policy=(
            "Total-return-adjusted OHLC is used. Yahoo dividend and split events are retained as "
            "metadata but are not separately applied, preventing double counting."
        ),
    )
    print(json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
