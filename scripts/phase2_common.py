"""Shared deterministic loaders for Phase 2 command modules."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.data.snapshots import DatasetSnapshotStore
from app.models.enums import AssetClass
from app.models.market import Asset
from app.strategies.base import Strategy
from app.strategies.reference import reference_strategies, strategy_from_spec
from app.universe import UniverseDefinition


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"configuration must be a JSON object: {path}")
    return payload


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def configured_assets(config: dict[str, Any]) -> dict[Asset, str]:
    assets: dict[Asset, str] = {}
    for item in config.get("assets", []):
        if not isinstance(item, dict):
            raise ValueError("each configured asset must be an object")
        asset = Asset(
            symbol=str(item["symbol"]),
            asset_class=AssetClass(str(item["asset_class"])),
            currency=str(item.get("currency", "USD")),
            exchange=str(item.get("exchange", "STOOQ")),
        )
        assets[asset] = str(item["provider_symbol"])
    if not assets:
        raise ValueError("configuration requires at least one asset")
    return assets


def resolve_universe(value: str) -> UniverseDefinition:
    direct = Path(value)
    path = direct if direct.is_file() else Path("config/universes") / f"{value}.json"
    return UniverseDefinition.model_validate(load_json(path))


def load_snapshot_bars(
    store: DatasetSnapshotStore, dataset_id: str
) -> dict[str, tuple[object, ...]]:
    manifest = store.load_manifest(dataset_id)
    return {
        item.asset.symbol: store.load_bars(dataset_id, item.asset.symbol)
        for item in manifest.instruments
    }


def strategy_for_asset(asset: Asset, family_index: int = 0) -> Strategy:
    reference = reference_strategies(asset.symbol)[family_index]
    spec = reference.spec.model_copy(
        update={"asset_class": asset.asset_class, "permitted_assets": (asset.symbol,)}
    )
    return strategy_from_spec(spec)
