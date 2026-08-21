"""List immutable local dataset snapshots without fetching remote data."""

import argparse
import json
from pathlib import Path

from app.data.snapshots import DatasetSnapshotStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    arguments = parser.parse_args()
    manifests = DatasetSnapshotStore(arguments.snapshot_root).list_manifests()
    print(
        json.dumps([manifest.public_metadata() for manifest in manifests], indent=2, sort_keys=True)
    )


if __name__ == "__main__":
    main()
