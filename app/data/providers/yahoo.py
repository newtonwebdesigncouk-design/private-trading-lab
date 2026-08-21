"""Credential-free, GET-only Yahoo historical chart adapter with corporate actions."""

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from urllib.parse import quote, urlencode

from app.data.models import (
    AssetMetadata,
    CorporateAction,
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
from app.models.enums import AdjustmentPolicy, AssetClass, CorporateActionType
from app.models.market import Asset, MarketBar

DEFAULT_YAHOO_ASSETS: Mapping[Asset, str] = {
    Asset(symbol="SPY", asset_class=AssetClass.ETF, exchange="YAHOO"): "SPY",
    Asset(symbol="QQQ", asset_class=AssetClass.ETF, exchange="YAHOO"): "QQQ",
    Asset(symbol="BTCUSD", asset_class=AssetClass.CRYPTOCURRENCY, exchange="YAHOO"): "BTC-USD",
    Asset(symbol="EURUSD", asset_class=AssetClass.FOREX, exchange="YAHOO"): "EURUSD=X",
    Asset(symbol="SPX", asset_class=AssetClass.INDEX, exchange="YAHOO"): "^GSPC",
}


class YahooReadOnlyProvider(MarketDataProvider):
    """Historical bars/actions only; no finance account or transaction endpoint exists."""

    name = "yahoo-chart-read-only"
    base_url = "https://query1.finance.yahoo.com/v8/finance/chart"

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
        self._symbols = dict(assets or DEFAULT_YAHOO_ASSETS)
        self._transport = transport or UrllibReadOnlyMarketDataTransport()
        self._maximum_attempts = maximum_attempts
        self._timeout_seconds = timeout_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._sleeper = sleeper

    def provider_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name=self.name,
            source_url="https://finance.yahoo.com/",
            version="chart-v8-v1",
            capabilities=ProviderCapabilities(
                asset_classes=frozenset(asset.asset_class for asset in self._symbols),
                intervals=("1d",),
                corporate_actions=True,
                requires_secret=False,
                read_only=True,
            ),
            configuration={
                "transport": "public-chart-http-get",
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
            raise ValueError(f"asset is not configured for Yahoo: {asset.symbol}") from exc
        return AssetMetadata(
            asset=asset,
            provider_symbol=symbol,
            timezone="UTC",
            supported_intervals=("1d",),
        )

    def _url(self, asset: Asset, start: datetime, end: datetime, interval: str) -> str:
        if interval != "1d":
            raise ValueError("Yahoo adapter supports only daily bars")
        symbol = quote(self.asset_metadata(asset).provider_symbol, safe="")
        query = urlencode(
            {
                "period1": int(start.timestamp()),
                "period2": int(end.timestamp()) + 1,
                "interval": "1d",
                "events": "div,splits",
                "includeAdjustedClose": "true",
            }
        )
        return f"{self.base_url}/{symbol}?{query}"

    def _download(self, url: str) -> bytes:
        for attempt in range(self._maximum_attempts):
            try:
                return self._transport.get(url, timeout_seconds=self._timeout_seconds)
            except ProviderTransportError as exc:
                retryable = exc.status_code in {408, 425, 429, 500, 502, 503, 504} or (
                    exc.status_code is None
                )
                if not retryable or attempt + 1 >= self._maximum_attempts:
                    raise
                self._sleeper(self._retry_delay_seconds * (2**attempt))
        raise ProviderTransportError("read-only provider retry loop failed")  # pragma: no cover

    @staticmethod
    def _daily_close_timestamp(epoch: int) -> datetime:
        """Use next-day UTC midnight so every daily bar is certainly complete and alignable."""
        source_date = datetime.fromtimestamp(epoch, tz=UTC).date()
        return datetime.combine(source_date + timedelta(days=1), datetime_time(0), tzinfo=UTC)

    @staticmethod
    def _extract(
        payload: bytes, asset: Asset
    ) -> tuple[tuple[RawMarketBar, ...], tuple[CorporateAction, ...]]:
        document = json.loads(payload)
        chart = document.get("chart", {})
        if chart.get("error"):
            raise ProviderTransportError(f"provider payload error: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            return (), ()
        result = results[0]
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quote_rows = indicators.get("quote") or []
        adjusted_rows = indicators.get("adjclose") or []
        quote_data = quote_rows[0] if quote_rows else {}
        adjusted_data = adjusted_rows[0] if adjusted_rows else {}
        adjusted_closes = adjusted_data.get("adjclose") or [None] * len(timestamps)
        rows: list[RawMarketBar] = []
        for index, epoch in enumerate(timestamps):
            try:
                raw_close = float(quote_data["close"][index])
                adjusted_close = float(adjusted_closes[index])
                factor = adjusted_close / raw_close
                volume = quote_data.get("volume", [0.0] * len(timestamps))[index] or 0.0
                rows.append(
                    RawMarketBar(
                        timestamp=YahooReadOnlyProvider._daily_close_timestamp(int(epoch)),
                        open=float(quote_data["open"][index]) * factor,
                        high=float(quote_data["high"][index]) * factor,
                        low=float(quote_data["low"][index]) * factor,
                        close=adjusted_close,
                        adjusted_close=adjusted_close,
                        volume=float(volume),
                    )
                )
            except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError):
                rows.append(
                    RawMarketBar(
                        timestamp=YahooReadOnlyProvider._daily_close_timestamp(int(epoch)),
                        open=-1,
                        high=-1,
                        low=-1,
                        close=-1,
                    )
                )
        actions: list[CorporateAction] = []
        events = result.get("events") or {}
        for event in (events.get("dividends") or {}).values():
            actions.append(
                CorporateAction(
                    asset=asset,
                    effective_timestamp=YahooReadOnlyProvider._daily_close_timestamp(
                        int(event["date"])
                    ),
                    action_type=CorporateActionType.CASH_DIVIDEND,
                    cash_amount=float(event["amount"]),
                    currency=asset.currency,
                    source="yahoo-chart-read-only",
                )
            )
        for event in (events.get("splits") or {}).values():
            numerator = float(event.get("numerator", 1))
            denominator = float(event.get("denominator", 1))
            actions.append(
                CorporateAction(
                    asset=asset,
                    effective_timestamp=YahooReadOnlyProvider._daily_close_timestamp(
                        int(event["date"])
                    ),
                    action_type=CorporateActionType.STOCK_SPLIT,
                    split_ratio=numerator / denominator,
                    currency=asset.currency,
                    source="yahoo-chart-read-only",
                    source_reference=str(event.get("splitRatio", "")),
                )
            )
        return tuple(rows), tuple(sorted(actions, key=lambda item: item.effective_timestamp))

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
        payload = self._download(self._url(asset, start, end, interval))
        raw_rows, actions = self._extract(payload, asset)
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
            provider_version="chart-v8-v1",
            asset=asset,
            interval=interval,
            requested_start=start,
            requested_end=end,
            bars=bars,
            corporate_actions=actions,
            raw_checksum=hashlib.sha256(payload).hexdigest(),
            diagnostics=diagnostics,
            adjustment_policy=AdjustmentPolicy.TOTAL_RETURN_ADJUSTED,
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

    def corporate_actions(
        self, asset: Asset, start: datetime, end: datetime
    ) -> tuple[CorporateAction, ...]:
        return self.historical_batch(asset, start, end).corporate_actions

    def latest_price(self, asset: Asset, as_of: datetime) -> MarketBar:
        bars = self.historical_data(asset, as_of - timedelta(days=14), as_of)
        if not bars:
            raise LookupError("no provider bar exists at or before as_of")
        return bars[-1]
