"""Deterministic synthetic market data with changing regimes."""

import hashlib
import math
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import ClassVar

import numpy as np

from app.data.cache import HistoricalDataCache
from app.data.provider import MarketDataProvider
from app.models.enums import AssetClass
from app.models.market import Asset, MarketBar

DEFAULT_ASSETS = (
    Asset(symbol="SYNTH_EQ", asset_class=AssetClass.EQUITY),
    Asset(symbol="SYNTH_ETF", asset_class=AssetClass.ETF),
    Asset(symbol="SYNTH_CRYPTO", asset_class=AssetClass.CRYPTOCURRENCY),
    Asset(symbol="SYNTH_FX", asset_class=AssetClass.FOREX),
    Asset(symbol="SYNTH_INDEX", asset_class=AssetClass.INDEX),
)


class SyntheticMarketDataProvider(MarketDataProvider):
    """Generates repeatable OHLCV bars; no network or provider credentials required."""

    name = "synthetic-v2"
    anchor = datetime(2000, 1, 1, 21, tzinfo=UTC)
    _series_cache: ClassVar[dict[tuple[int, str], tuple[date, tuple[MarketBar, ...]]]] = {}

    def __init__(self, seed: int = 1729, cache_dir: Path | None = None) -> None:
        self.seed = seed
        self.cache = HistoricalDataCache(cache_dir) if cache_dir is not None else None

    def supported_assets(self) -> tuple[Asset, ...]:
        return DEFAULT_ASSETS

    def _asset_seed(self, asset: Asset) -> int:
        digest = hashlib.sha256(f"{self.seed}:{asset.cache_key}".encode()).digest()
        return int.from_bytes(digest[:8], "big")

    @staticmethod
    def _normalise(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start and end must be timezone-aware")
        return value.astimezone(UTC)

    def historical_data(
        self,
        asset: Asset,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> tuple[MarketBar, ...]:
        start, end = self._normalise(start), self._normalise(end)
        if interval != "1d":
            raise ValueError("the synthetic v1 provider supports only 1d bars")
        if start >= end:
            raise ValueError("start must precede end")
        if asset not in self.supported_assets():
            raise ValueError(f"unsupported synthetic asset: {asset.symbol}")

        if self.cache is not None:
            cached = self.cache.get(asset, start, end, interval, self.name)
            if cached is not None:
                return cached

        series = self._series_through(asset, end)
        result = tuple(bar for bar in series if start <= bar.timestamp <= end)
        if self.cache is not None:
            self.cache.put(asset, start, end, interval, self.name, result)
        return result

    def _series_through(self, asset: Asset, end: datetime) -> tuple[MarketBar, ...]:
        key = (self.seed, asset.cache_key)
        cached = self._series_cache.get(key)
        if cached is not None and cached[0] >= end.date():
            return cached[1]

        rng = np.random.default_rng(self._asset_seed(asset))
        price = 100.0
        previous_close = price
        bars: list[MarketBar] = []
        current = self.anchor.date()
        index = 0
        while current <= end.date():
            if asset.asset_class is not AssetClass.CRYPTOCURRENCY and current.weekday() >= 5:
                current += timedelta(days=1)
                continue
            timestamp = datetime.combine(current, time(21), tzinfo=UTC)
            phase = index % 360
            if phase < 120:
                drift, volatility = 0.0008, 0.009
            elif phase < 210:
                drift, volatility = -0.0010, 0.018
            elif phase < 300:
                drift, volatility = 0.0000, 0.006
            else:
                drift, volatility = 0.0004, 0.026
            cyclical = 0.0015 * math.sin(index / 13.0)
            overnight = float(rng.normal(0.0, volatility * 0.25))
            intraday = float(rng.normal(drift + cyclical, volatility))
            open_price = max(1.0, previous_close * math.exp(overnight))
            close = max(1.0, open_price * math.exp(intraday))
            wick = abs(float(rng.normal(0.0, volatility * 0.45)))
            high = max(open_price, close) * (1.0 + wick)
            low = min(open_price, close) * max(0.1, 1.0 - wick)
            volume = max(0.0, 1_000_000.0 * (1 + float(rng.normal(0.0, 0.15))))
            dividend = (
                0.15
                if asset.asset_class in {AssetClass.EQUITY, AssetClass.ETF}
                and index > 0
                and index % 63 == 0
                else 0.0
            )
            price = close
            previous_close = price
            bars.append(
                MarketBar(
                    timestamp=timestamp,
                    open=round(open_price, 6),
                    high=round(high, 6),
                    low=round(low, 6),
                    close=round(close, 6),
                    adjusted_close=round(close, 6),
                    volume=round(volume, 2),
                    asset=asset,
                    source=self.name,
                    interval="1d",
                    dividend=dividend,
                )
            )
            index += 1
            current += timedelta(days=1)
        result = tuple(bars)
        self._series_cache[key] = (end.date(), result)
        return result

    def latest_price(self, asset: Asset, as_of: datetime) -> MarketBar:
        as_of = self._normalise(as_of)
        bars = self.historical_data(asset, as_of - timedelta(days=14), as_of)
        if not bars:
            raise LookupError("no synthetic bar exists at or before as_of")
        return bars[-1]
