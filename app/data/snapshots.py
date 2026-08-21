"""Content-addressed immutable JSONL snapshots and checksum-verified loading."""

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.data.models import (
    CorporateAction,
    DatasetFreshness,
    DatasetManifest,
    HistoricalDataBatch,
    InstrumentSnapshot,
)
from app.data.provider import MarketDataProvider
from app.models.market import Asset, MarketBar


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _jsonl(items: Sequence[dict[str, Any]]) -> bytes:
    return ("\n".join(_canonical_json(item) for item in items) + "\n").encode()


def _manifest_checksum(manifest: DatasetManifest) -> str:
    payload = manifest.model_dump(mode="json", exclude={"manifest_checksum"})
    return _checksum(_canonical_json(payload).encode())


class DatasetSnapshotStore:
    """Writes once, verifies always; research loads by manifest ID without refetching."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def freeze(
        self,
        dataset_name: str,
        batches: Sequence[HistoricalDataBatch],
        *,
        code_revision: str,
        corporate_action_policy: str,
    ) -> DatasetManifest:
        if not dataset_name.strip():
            raise ValueError("dataset_name is required")
        if not batches:
            raise ValueError("at least one historical batch is required")
        if any(not batch.bars for batch in batches):
            raise ValueError("cannot freeze an empty or unusable historical batch")
        ordered = tuple(sorted(batches, key=lambda item: item.asset.cache_key))
        first = ordered[0]
        if any(
            batch.provider != first.provider
            or batch.provider_version != first.provider_version
            or batch.interval != first.interval
            or batch.adjustment_policy is not first.adjustment_policy
            for batch in ordered
        ):
            raise ValueError("all batches in a snapshot must share provider, interval, and policy")

        artifacts: list[tuple[HistoricalDataBatch, str, bytes, str | None, bytes | None]] = []
        identity_instruments: list[dict[str, object]] = []
        for batch in ordered:
            bar_payload = _jsonl([bar.model_dump(mode="json") for bar in batch.bars])
            canonical_checksum = _checksum(bar_payload)
            action_payload = (
                _jsonl([item.model_dump(mode="json") for item in batch.corporate_actions])
                if batch.corporate_actions
                else None
            )
            action_checksum = _checksum(action_payload) if action_payload is not None else None
            artifact = f"{batch.asset.cache_key}.bars.jsonl"
            action_artifact = (
                f"{batch.asset.cache_key}.actions.jsonl" if action_payload is not None else None
            )
            artifacts.append((batch, artifact, bar_payload, action_artifact, action_payload))
            identity_instruments.append(
                {
                    "asset": batch.asset.model_dump(mode="json"),
                    "raw_checksum": batch.raw_checksum,
                    "canonical_checksum": canonical_checksum,
                    "action_checksum": action_checksum,
                }
            )

        identity = {
            "dataset_name": dataset_name,
            "provider": first.provider,
            "provider_version": first.provider_version,
            "interval": first.interval,
            "requested_start": first.requested_start.isoformat(),
            "requested_end": first.requested_end.isoformat(),
            "adjustment_policy": first.adjustment_policy.value,
            "corporate_action_policy": corporate_action_policy,
            "provider_configuration": first.provider_configuration,
            "instruments": identity_instruments,
        }
        digest = _checksum(_canonical_json(identity).encode())[:16]
        dataset_id = f"{dataset_name}-{digest}"
        target = self.root / dataset_id
        if target.exists():
            return self.load_manifest(dataset_id)

        instrument_snapshots: list[InstrumentSnapshot] = []
        for batch, artifact, payload, action_artifact, action_payload in artifacts:
            instrument_snapshots.append(
                InstrumentSnapshot(
                    asset=batch.asset,
                    rows=len(batch.bars),
                    actual_start=batch.bars[0].timestamp,
                    actual_end=batch.bars[-1].timestamp,
                    raw_checksum=batch.raw_checksum,
                    canonical_checksum=_checksum(payload),
                    artifact=artifact,
                    corporate_action_rows=len(batch.corporate_actions),
                    corporate_action_checksum=(
                        _checksum(action_payload) if action_payload is not None else None
                    ),
                    corporate_action_artifact=action_artifact,
                    diagnostics=batch.diagnostics,
                )
            )
        manifest = DatasetManifest(
            dataset_id=dataset_id,
            dataset_version=digest,
            provider=first.provider,
            provider_version=first.provider_version,
            instruments=tuple(instrument_snapshots),
            asset_classes=tuple(
                sorted({batch.asset.asset_class for batch in ordered}, key=lambda item: item.value)
            ),
            interval=first.interval,
            requested_start=min(batch.requested_start for batch in ordered),
            requested_end=max(batch.requested_end for batch in ordered),
            actual_start=min(batch.bars[0].timestamp for batch in ordered),
            actual_end=max(batch.bars[-1].timestamp for batch in ordered),
            adjustment_policy=first.adjustment_policy,
            corporate_action_policy=corporate_action_policy,
            ingested_at=max(batch.fetched_at for batch in ordered),
            provider_configuration=dict(first.provider_configuration),
            code_revision=code_revision,
            manifest_checksum="pending",
        )
        manifest = manifest.model_copy(update={"manifest_checksum": _manifest_checksum(manifest)})

        self.root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=self.root))
        try:
            for _, artifact, payload, action_artifact, action_payload in artifacts:
                (temporary / artifact).write_bytes(payload)
                if action_artifact is not None and action_payload is not None:
                    (temporary / action_artifact).write_bytes(action_payload)
            (temporary / "manifest.json").write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return manifest

    def load_manifest(self, dataset_id: str) -> DatasetManifest:
        path = self.root / dataset_id / "manifest.json"
        if not path.is_file():
            raise FileNotFoundError(f"dataset manifest not found: {dataset_id}")
        manifest = DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if manifest.dataset_id != dataset_id:
            raise ValueError("dataset directory and manifest ID differ")
        if _manifest_checksum(manifest) != manifest.manifest_checksum:
            raise ValueError("dataset manifest checksum mismatch")
        return manifest

    def load_bars(self, dataset_id: str, symbol: str) -> tuple[MarketBar, ...]:
        manifest = self.load_manifest(dataset_id)
        instrument = next(
            (item for item in manifest.instruments if item.asset.symbol == symbol), None
        )
        if instrument is None:
            raise KeyError(f"instrument is not in dataset: {symbol}")
        payload = (self.root / dataset_id / instrument.artifact).read_bytes()
        if _checksum(payload) != instrument.canonical_checksum:
            raise ValueError(f"canonical data checksum mismatch for {symbol}")
        return tuple(
            MarketBar.model_validate_json(line) for line in payload.decode().splitlines() if line
        )

    def load_actions(self, dataset_id: str, symbol: str) -> tuple[CorporateAction, ...]:
        manifest = self.load_manifest(dataset_id)
        instrument = next(
            (item for item in manifest.instruments if item.asset.symbol == symbol), None
        )
        if instrument is None:
            raise KeyError(f"instrument is not in dataset: {symbol}")
        if instrument.corporate_action_artifact is None:
            return ()
        payload = (self.root / dataset_id / instrument.corporate_action_artifact).read_bytes()
        if _checksum(payload) != instrument.corporate_action_checksum:
            raise ValueError(f"corporate-action checksum mismatch for {symbol}")
        return tuple(
            CorporateAction.model_validate_json(line)
            for line in payload.decode().splitlines()
            if line
        )

    def validate(self, dataset_id: str) -> tuple[str, ...]:
        manifest = self.load_manifest(dataset_id)
        warnings: list[str] = []
        for instrument in manifest.instruments:
            bars = self.load_bars(dataset_id, instrument.asset.symbol)
            if len(bars) != instrument.rows:
                raise ValueError(f"row count mismatch for {instrument.asset.symbol}")
            self.load_actions(dataset_id, instrument.asset.symbol)
            warnings.extend(instrument.diagnostics.warnings)
        return tuple(warnings)

    def list_manifests(self) -> tuple[DatasetManifest, ...]:
        if not self.root.exists():
            return ()
        manifests = [
            self.load_manifest(path.name)
            for path in self.root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]
        return tuple(sorted(manifests, key=lambda item: item.dataset_id))

    def freshness(
        self, dataset_id: str, *, as_of: datetime, maximum_age: timedelta
    ) -> DatasetFreshness:
        if maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        manifest = self.load_manifest(dataset_id)
        if as_of.tzinfo is None or manifest.actual_end.tzinfo is None:
            raise ValueError("freshness timestamps must be timezone-aware")
        age = max((as_of - manifest.actual_end).total_seconds(), 0.0)
        return DatasetFreshness(
            dataset_id=dataset_id,
            latest_observation=manifest.actual_end,
            evaluated_at=as_of,
            age_seconds=age,
            maximum_age_seconds=maximum_age.total_seconds(),
            stale=age > maximum_age.total_seconds(),
        )


class DatasetIngestor:
    def __init__(self, store: DatasetSnapshotStore) -> None:
        self.store = store

    def ingest(
        self,
        provider: MarketDataProvider,
        assets: Sequence[Asset],
        start: object,
        end: object,
        *,
        interval: str,
        dataset_name: str,
        code_revision: str,
        corporate_action_policy: str,
    ) -> DatasetManifest:
        from datetime import datetime

        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise TypeError("start and end must be datetime instances")
        batches = tuple(provider.historical_batch(asset, start, end, interval) for asset in assets)
        return self.store.freeze(
            dataset_name,
            batches,
            code_revision=code_revision,
            corporate_action_policy=corporate_action_policy,
        )
