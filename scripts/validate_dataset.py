"""Verify a frozen manifest and every referenced artifact checksum."""

import argparse
import json
from pathlib import Path

from app.data.snapshots import DatasetSnapshotStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    arguments = parser.parse_args()
    store = DatasetSnapshotStore(arguments.snapshot_root)
    warnings = store.validate(arguments.dataset)
    manifest = store.load_manifest(arguments.dataset)
    print(
        json.dumps(
            {
                "dataset_id": manifest.dataset_id,
                "valid": True,
                "rows": manifest.row_counts,
                "warnings": warnings,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
