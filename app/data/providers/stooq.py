"""Narrow read-only Stooq daily-history adapter.

The only outbound request in the application is an HTTP GET for public CSV history.
This module has no account, order, funding, credential, or write capability.
"""

import csv
import hashlib
import io
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from urllib.parse import urlencode

from app.data.models import (
    AssetMetadata,
    HistoricalDataBatch,
    ProviderCapabilities,
    ProviderMetadata,
    RawMarketBar,
)
from app.data.normalization import normalise_bars
from app.data.provider import MarketDataProvider
from app.data.providers.transport import (
    ProviderTransportError,
    ReadOnlyMarketDataTransport,
    UrllibReadOnlyMarketDataTransport,
)
from app.models.enums import AdjustmentPolicy, AssetClass
from app.models.market import Asset, MarketBar

DEFAULT_STOOQ_ASSETS: Mapping[Asset, str] = {
    Asset(symbol="SPY", asset_class=AssetClass.ETF, exchange="STOOQ"): "spy.us",
    Asset(symbol="QQQ", asset_class=AssetClass.ETF, exchange="STOOQ"): "qqq.us",
    Asset(symbol="BTCUSD", asset_class=AssetClass.CRYPTOCURRENCY, exchange="STOOQ"): "btcusd",
    Asset(symbol="EURUSD", asset_class=AssetClass.FOREX, exchange="STOOQ"): "eurusd",
    Asset(symbol="SPX", asset_class=AssetClass.INDEX, exchange="STOOQ"): "^spx",
}


class StooqReadOnlyProvider(MarketDataProvider):
    """Public, credential-free, daily CSV ingestion with bounded deterministic retries."""

    name = "stooq-read-only"
    base_url = "https://stooq.com/q/d/l/"

    def __init__(
        self,
        assets: Mapping[Asset, str] | None = None,
        *,
        transport: ReadOnlyMarketDataTransport | None = None,
        maximum_attempts: int = 3,
        timeout_seconds: float = 20.0,
        retry_delay_seconds: float = 0.25,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        self._symbols = dict(assets or DEFAULT_STOOQ_ASSETS)
        self._transport = transport or UrllibReadOnlyMarketDataTransport()
        self._maximum_attempts = maximum_attempts
        self._timeout_seconds = timeout_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._sleeper = sleeper

    def provider_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name=self.name,
            source_url="https://stooq.com/",
            version="daily-csv-v1",
            capabilities=ProviderCapabilities(
                asset_classes=frozenset(asset.asset_class for asset in self._symbols),
                intervals=("1d",),
                corporate_actions=False,
                requires_secret=False,
                read_only=True,
            ),
            configuration={
                "transport": "public-csv-http-get",
                "maximum_attempts": self._maximum_attempts,
                "timeout_seconds": self._timeout_seconds,
            },
        )

    def supported_assets(self) -> tuple[Asset, ...]:
        return tuple(sorted(self._symbols, key=lambda asset: asset.cache_key))

    def asset_metadata(self, asset: Asset) -> AssetMetadata:
        try:
            symbol = self._symbols[asset]
        except KeyError as exc:
            raise ValueError(f"asset is not configured for Stooq: {asset.symbol}") from exc
        return AssetMetadata(
            asset=asset,
            provider_symbol=symbol,
            timezone="UTC",
            supported_intervals=("1d",),
        )

    def _url(self, asset: Asset, start: datetime, end: datetime, interval: str) -> str:
        if interval != "1d":
            raise ValueError("Stooq adapter supports only daily bars")
        metadata = self.asset_metadata(asset)
        query = urlencode(
            {
                "s": metadata.provider_symbol,
                "d1": start.strftime("%Y%m%d"),
                "d2": end.strftime("%Y%m%d"),
                "i": "d",
            }
        )
        return f"{self.base_url}?{query}"

    def _download(self, url: str) -> bytes:
        errors: list[str] = []
        for attempt in range(self._maximum_attempts):
            try:
                return self._transport.get(url, timeout_seconds=self._timeout_seconds)
            except ProviderTransportError as exc:
                errors.append(str(exc))
                retryable = exc.status_code in {408, 425, 429, 500, 502, 503, 504} or (
                    exc.status_code is None
                )
                if not retryable or attempt + 1 >= self._maximum_attempts:
                    raise
                self._sleeper(self._retry_delay_seconds * (2**attempt))
        raise ProviderTransportError("; ".join(errors))  # pragma: no cover

    @staticmethod
    def _parse(payload: bytes) -> tuple[RawMarketBar, ...]:
        text = payload.decode("utf-8-sig").strip()
        if not text or text.lower().startswith("no data"):
            return ()
        if text.lstrip().lower().startswith("<!doctype") or text.lstrip().lower().startswith(
            "<html"
        ):
            return (
                RawMarketBar(
                    timestamp=datetime(1970, 1, 1, tzinfo=UTC),
                    open=-1,
                    high=-1,
                    low=-1,
                    close=-1,
                ),
            )
        rows: list[RawMarketBar] = []
        for record in csv.DictReader(io.StringIO(text)):
            lowered = {str(key).strip().lower(): value for key, value in record.items()}
            try:
                date_value = datetime.strptime(lowered["date"], "%Y-%m-%d").date()
                volume_text = lowered.get("volume") or "0"
                rows.append(
                    RawMarketBar(
                        timestamp=datetime.combine(date_value, datetime_time(0), tzinfo=UTC),
                        open=float(lowered["open"]),
                        high=float(lowered["high"]),
                        low=float(lowered["low"]),
                        close=float(lowered["close"]),
                        volume=float(volume_text),
                    )
                )
            except (KeyError, TypeError, ValueError):
                # Preserve a deterministic invalid sentinel for the normaliser to report.
                rows.append(
                    RawMarketBar(
                        timestamp=datetime(1970, 1, 1, tzinfo=UTC),
                        open=-1,
                        high=-1,
                        low=-1,
                        close=-1,
                    )
                )
        return tuple(rows)

    def historical_batch(
        self,
        asset: Asset,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> HistoricalDataBatch:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if start >= end:
            raise ValueError("start must precede end")
        url = self._url(asset, start, end, interval)
        payload = self._download(url)
        raw_rows = self._parse(payload)
        bars, diagnostics = normalise_bars(
            raw_rows, asset=asset, source=self.name, interval=interval
        )
        bars = tuple(bar for bar in bars if start <= bar.timestamp <= end)
        diagnostics = diagnostics.model_copy(
            update={
                "output_rows": len(bars),
                "partial_response": diagnostics.partial_response or not bars,
                "warnings": diagnostics.warnings
                + (("provider returned no usable bars",) if not bars else ()),
            }
        )
        return HistoricalDataBatch(
            provider=self.name,
            provider_version="daily-csv-v1",
            asset=asset,
            interval=interval,
            requested_start=start,
            requested_end=end,
            bars=bars,
            raw_checksum=hashlib.sha256(payload).hexdigest(),
            diagnostics=diagnostics,
            adjustment_policy=AdjustmentPolicy.SPLIT_ADJUSTED_WITH_CASH_DIVIDENDS,
            provider_configuration=self.provider_metadata().configuration,
        )

    def historical_data(
        self,
        asset: Asset,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> tuple[MarketBar, ...]:
        return self.historical_batch(asset, start, end, interval).bars

    def latest_price(self, asset: Asset, as_of: datetime) -> MarketBar:
        bars = self.historical_data(asset, as_of - timedelta(days=14), as_of)
        if not bars:
            raise LookupError("no provider bar exists at or before as_of")
        return bars[-1]
