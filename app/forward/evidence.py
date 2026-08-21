"""Append-only current/replay evidence with checksummed, provenance-safe manifests."""

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from app.data.provider import MarketDataProvider
from app.forward.models import (
    ForwardDataPolicy,
    ForwardEvidenceInstrument,
    ForwardEvidenceManifest,
    IncrementalEvidenceResult,
    canonical_hash,
)
from app.models.enums import ObservationProvenance
from app.models.market import Asset, MarketBar


class ForwardDataQualityError(RuntimeError):
    """Fail-closed signal for stale, incomplete, future, or inconsistent evidence."""


def _canonical_bytes(items: Sequence[MarketBar]) -> bytes:
    lines = [
        json.dumps(
            bar.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        for bar in items
    ]
    return ("\n".join(lines) + "\n").encode()


def _manifest_checksum(manifest: ForwardEvidenceManifest) -> str:
    payload = manifest.model_dump(mode="json", exclude={"manifest_checksum"})
    return canonical_hash(payload)


class ForwardEvidenceStore:
    """Each update is a new immutable directory linked to its predecessor."""

    _safe_name = re.compile(r"^[A-Za-z0-9_.-]+$")

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def _validate_name(cls, value: str, label: str) -> None:
        if not value or cls._safe_name.fullmatch(value) is None:
            raise ValueError(f"unsafe {label}")

    def _stream_root(self, stream_id: str) -> Path:
        self._validate_name(stream_id, "evidence stream ID")
        return self.root / stream_id

    def list_manifests(self, stream_id: str) -> tuple[ForwardEvidenceManifest, ...]:
        stream_root = self._stream_root(stream_id)
        if not stream_root.exists():
            return ()
        manifests: list[ForwardEvidenceManifest] = []
        for directory in stream_root.iterdir():
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            path = directory / "manifest.json"
            manifest = ForwardEvidenceManifest.model_validate_json(path.read_text(encoding="utf-8"))
            if manifest.stream_id != stream_id or not directory.name.endswith(manifest.manifest_id):
                raise ForwardDataQualityError("evidence directory identity mismatch")
            if _manifest_checksum(manifest) != manifest.manifest_checksum:
                raise ForwardDataQualityError("forward evidence manifest checksum mismatch")
            manifests.append(manifest)
        ordered = tuple(sorted(manifests, key=lambda item: item.sequence))
        previous: str | None = None
        for sequence, manifest in enumerate(ordered, start=1):
            if manifest.sequence != sequence or manifest.previous_manifest_id != previous:
                raise ForwardDataQualityError("forward evidence chain is incomplete")
            previous = manifest.manifest_id
        return ordered

    def latest_manifest(self, stream_id: str) -> ForwardEvidenceManifest | None:
        manifests = self.list_manifests(stream_id)
        return manifests[-1] if manifests else None

    def _directory_for(self, stream_id: str, manifest: ForwardEvidenceManifest) -> Path:
        return self._stream_root(stream_id) / f"{manifest.sequence:08d}-{manifest.manifest_id}"

    def load_manifest_bars(
        self, stream_id: str, manifest_id: str
    ) -> dict[str, tuple[MarketBar, ...]]:
        self._validate_name(manifest_id, "evidence manifest ID")
        manifest = next(
            (item for item in self.list_manifests(stream_id) if item.manifest_id == manifest_id),
            None,
        )
        if manifest is None:
            raise FileNotFoundError(f"forward evidence manifest not found: {manifest_id}")
        directory = self._directory_for(stream_id, manifest)
        result: dict[str, tuple[MarketBar, ...]] = {}
        for instrument in manifest.instruments:
            payload = (directory / instrument.artifact).read_bytes()
            if canonical_hash(payload.decode()) != instrument.canonical_checksum:
                raise ForwardDataQualityError("forward evidence artifact checksum mismatch")
            bars = tuple(
                MarketBar.model_validate_json(line)
                for line in payload.decode().splitlines()
                if line
            )
            if len(bars) != instrument.rows:
                raise ForwardDataQualityError("forward evidence row count mismatch")
            result[instrument.asset.symbol] = bars
        return result

    def load_all_bars(self, stream_id: str) -> dict[str, tuple[MarketBar, ...]]:
        combined: dict[str, list[MarketBar]] = {}
        for manifest in self.list_manifests(stream_id):
            for symbol, bars in self.load_manifest_bars(stream_id, manifest.manifest_id).items():
                target = combined.setdefault(symbol, [])
                if target and bars and bars[0].timestamp <= target[-1].timestamp:
                    raise ForwardDataQualityError("forward evidence contains duplicate chronology")
                target.extend(bars)
        return {symbol: tuple(bars) for symbol, bars in combined.items()}

    def append(
        self,
        *,
        stream_id: str,
        bars_by_symbol: Mapping[str, Sequence[MarketBar]],
        raw_checksums: Mapping[str, str],
        warnings: Mapping[str, Sequence[str]],
        provenance: ObservationProvenance,
        source_dataset_id: str | None,
        provider_name: str,
        provider_version: str,
        interval: str,
        requested_start: datetime,
        requested_end: datetime,
        fetched_at: datetime,
        code_revision: str,
    ) -> IncrementalEvidenceResult:
        if requested_start.tzinfo is None or requested_end.tzinfo is None:
            raise ValueError("evidence request timestamps must be timezone-aware")
        previous = self.latest_manifest(stream_id)
        prior_bars = self.load_all_bars(stream_id) if previous is not None else {}
        filtered: dict[str, tuple[MarketBar, ...]] = {}
        for symbol, values in sorted(bars_by_symbol.items()):
            ordered = tuple(sorted(values, key=lambda item: item.timestamp))
            if len({bar.timestamp for bar in ordered}) != len(ordered):
                raise ForwardDataQualityError("duplicate bars in incremental evidence update")
            if any(bar.timestamp > requested_end for bar in ordered):
                raise ForwardDataQualityError("future bar rejected from forward evidence")
            prior_end = prior_bars.get(symbol, ())[-1].timestamp if prior_bars.get(symbol) else None
            new = tuple(
                bar
                for bar in ordered
                if bar.timestamp >= requested_start
                and (prior_end is None or bar.timestamp > prior_end)
            )
            if new:
                filtered[symbol] = new
        if not filtered:
            return IncrementalEvidenceResult(
                manifest=previous,
                new_bars={},
                created=False,
                warnings=tuple(message for values in warnings.values() for message in values),
            )

        sequence = 1 if previous is None else previous.sequence + 1
        identity_instruments: list[dict[str, object]] = []
        artifact_payloads: dict[str, bytes] = {}
        instruments: list[ForwardEvidenceInstrument] = []
        for symbol, bars in sorted(filtered.items()):
            payload = _canonical_bytes(bars)
            checksum = canonical_hash(payload.decode())
            artifact = f"{bars[0].asset.cache_key}.bars.jsonl"
            artifact_payloads[artifact] = payload
            instrument = ForwardEvidenceInstrument(
                asset=bars[0].asset,
                rows=len(bars),
                actual_start=bars[0].timestamp,
                actual_end=bars[-1].timestamp,
                raw_checksum=raw_checksums.get(symbol, checksum),
                canonical_checksum=checksum,
                artifact=artifact,
                warnings=tuple(warnings.get(symbol, ())),
            )
            instruments.append(instrument)
            identity_instruments.append(instrument.model_dump(mode="json"))
        identity = {
            "stream_id": stream_id,
            "sequence": sequence,
            "previous_manifest_id": previous.manifest_id if previous else None,
            "provenance": provenance.value,
            "source_dataset_id": source_dataset_id,
            "provider_name": provider_name,
            "provider_version": provider_version,
            "interval": interval,
            "requested_start": requested_start.isoformat(),
            "requested_end": requested_end.isoformat(),
            "instruments": identity_instruments,
        }
        manifest_id = f"forward-evidence-{canonical_hash(identity)[:20]}"
        manifest = ForwardEvidenceManifest(
            manifest_id=manifest_id,
            stream_id=stream_id,
            sequence=sequence,
            previous_manifest_id=previous.manifest_id if previous else None,
            provenance=provenance,
            source_dataset_id=source_dataset_id,
            provider_name=provider_name,
            provider_version=provider_version,
            interval=interval,
            requested_start=requested_start,
            requested_end=requested_end,
            fetched_at=fetched_at,
            instruments=tuple(instruments),
            code_revision=code_revision,
            manifest_checksum="pending",
        )
        manifest = manifest.model_copy(update={"manifest_checksum": _manifest_checksum(manifest)})
        target = self._directory_for(stream_id, manifest)
        if target.exists():
            return IncrementalEvidenceResult(manifest=manifest, new_bars=filtered, created=False)
        stream_root = self._stream_root(stream_id)
        stream_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".forward-evidence-", dir=stream_root))
        try:
            for artifact, payload in artifact_payloads.items():
                (temporary / artifact).write_bytes(payload)
            (temporary / "manifest.json").write_text(
                json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return IncrementalEvidenceResult(manifest=manifest, new_bars=filtered, created=True)


def evidence_stream_id(
    portfolio_id: str,
    provenance: ObservationProvenance,
    assets: Sequence[Asset],
    data_policy: ForwardDataPolicy,
) -> str:
    identity = {
        "portfolio_id": portfolio_id,
        "provenance": provenance.value,
        "assets": [
            asset.model_dump(mode="json") for asset in sorted(assets, key=lambda x: x.cache_key)
        ],
        "data_policy": data_policy.model_dump(mode="json"),
    }
    return f"forward-stream-{canonical_hash(identity)[:20]}"


class IncrementalMarketDataCollector:
    """Calls only the approved provider interface; it contains no network implementation."""

    def __init__(
        self,
        provider: MarketDataProvider,
        store: ForwardEvidenceStore,
        *,
        code_revision: str,
    ) -> None:
        self.provider = provider
        self.store = store
        self.code_revision = code_revision

    def collect(
        self,
        *,
        stream_id: str,
        assets: Sequence[Asset],
        forward_start: datetime,
        as_of: datetime,
        data_policy: ForwardDataPolicy,
    ) -> IncrementalEvidenceResult:
        metadata = self.provider.provider_metadata()
        if not metadata.capabilities.read_only or metadata.capabilities.requires_secret:
            raise ForwardDataQualityError("forward provider must be credential-free and read-only")
        if (
            metadata.name != data_policy.provider_name
            or metadata.version != data_policy.provider_version
        ):
            raise ForwardDataQualityError("provider does not match the frozen trial data policy")
        if data_policy.interval not in metadata.capabilities.intervals:
            raise ForwardDataQualityError("provider does not support the frozen interval")
        existing = self.store.load_all_bars(stream_id)
        collected: dict[str, tuple[MarketBar, ...]] = {}
        raw_checksums: dict[str, str] = {}
        warnings: dict[str, tuple[str, ...]] = {}
        fetched_at = as_of
        for asset in sorted(assets, key=lambda item: item.cache_key):
            prior = existing.get(asset.symbol, ())
            if prior and prior[-1].timestamp >= as_of:
                if as_of - prior[-1].timestamp > data_policy.maximum_staleness:
                    raise ForwardDataQualityError(f"provider data is stale for {asset.symbol}")
                continue
            request_start = max(forward_start, prior[-1].timestamp) if prior else forward_start
            batch = self.provider.historical_batch(
                asset, request_start, as_of, data_policy.interval
            )
            fetched_at = max(fetched_at, batch.fetched_at)
            if not batch.diagnostics.valid:
                raise ForwardDataQualityError(
                    f"provider returned invalid/partial data for {asset.symbol}"
                )
            if data_policy.reject_gaps and batch.diagnostics.missing_expected_timestamps:
                raise ForwardDataQualityError(f"provider data contains gaps for {asset.symbol}")
            new = tuple(
                bar
                for bar in batch.bars
                if bar.timestamp >= forward_start
                and bar.timestamp <= as_of
                and (not prior or bar.timestamp > prior[-1].timestamp)
            )
            latest = new[-1].timestamp if new else (prior[-1].timestamp if prior else None)
            if latest is None or as_of - latest > data_policy.maximum_staleness:
                raise ForwardDataQualityError(f"provider data is stale for {asset.symbol}")
            if new:
                collected[asset.symbol] = new
            raw_checksums[asset.symbol] = batch.raw_checksum
            warnings[asset.symbol] = batch.diagnostics.warnings
        return self.store.append(
            stream_id=stream_id,
            bars_by_symbol=collected,
            raw_checksums=raw_checksums,
            warnings=warnings,
            provenance=ObservationProvenance.GENUINE_FORWARD,
            source_dataset_id=None,
            provider_name=metadata.name,
            provider_version=metadata.version,
            interval=data_policy.interval,
            requested_start=forward_start,
            requested_end=as_of,
            fetched_at=fetched_at,
            code_revision=self.code_revision,
        )


def append_replay_evidence(
    store: ForwardEvidenceStore,
    *,
    stream_id: str,
    source_dataset_id: str,
    bars_by_symbol: Mapping[str, Sequence[MarketBar]],
    timestamp: datetime,
    code_revision: str,
) -> IncrementalEvidenceResult:
    """Replay evidence is explicitly labelled and cannot masquerade as genuine forward data."""
    return store.append(
        stream_id=stream_id,
        bars_by_symbol=bars_by_symbol,
        raw_checksums={},
        warnings={},
        provenance=ObservationProvenance.REPLAY,
        source_dataset_id=source_dataset_id,
        provider_name="immutable-historical-replay",
        provider_version="phase3-replay-v1",
        interval="1d",
        requested_start=timestamp,
        requested_end=timestamp,
        fetched_at=timestamp,
        code_revision=code_revision,
    )
