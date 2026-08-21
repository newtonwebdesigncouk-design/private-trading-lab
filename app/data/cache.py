"""Simple auditable JSON cache for immutable historical responses."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.models.market import Asset, MarketBar


class HistoricalDataCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(
        self, asset: Asset, start: datetime, end: datetime, interval: str, provider: str
    ) -> Path:
        raw = "|".join(
            [asset.cache_key, start.isoformat(), end.isoformat(), interval, provider]
        ).encode()
        digest = hashlib.sha256(raw).hexdigest()[:20]
        return self.root / asset.cache_key / f"{digest}.json"

    def get(
        self, asset: Asset, start: datetime, end: datetime, interval: str, provider: str
    ) -> tuple[MarketBar, ...] | None:
        path = self._path(asset, start, end, interval, provider)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return tuple(MarketBar.model_validate(item) for item in payload["bars"])

    def put(
        self,
        asset: Asset,
        start: datetime,
        end: datetime,
        interval: str,
        provider: str,
        bars: tuple[MarketBar, ...],
    ) -> Path:
        path = self._path(asset, start, end, interval, provider)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "provider": provider,
            "bars": [bar.model_dump(mode="json") for bar in bars],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path
