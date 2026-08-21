"""Provider-neutral market data contract."""

import hashlib
import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from app.data.models import (
    AssetMetadata,
    CorporateAction,
    DataQualityDiagnostics,
    HistoricalDataBatch,
    ProviderMetadata,
)
from app.models.enums import AdjustmentPolicy
from app.models.market import Asset, MarketBar


class MarketDataProvider(ABC):
    @abstractmethod
    def provider_metadata(self) -> ProviderMetadata:
        """Describe the provider's source and explicitly bounded read-only capabilities."""

    @abstractmethod
    def historical_data(
        self,
        asset: Asset,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> tuple[MarketBar, ...]:
        """Return ascending bars whose close timestamps lie in the requested period."""

    @abstractmethod
    def latest_price(self, asset: Asset, as_of: datetime) -> MarketBar:
        """Return the latest bar available at or before ``as_of``."""

    @abstractmethod
    def supported_assets(self) -> tuple[Asset, ...]:
        """List assets available from this provider."""

    def supported_intervals(self) -> tuple[str, ...]:
        return self.provider_metadata().capabilities.intervals

    def asset_metadata(self, asset: Asset) -> AssetMetadata:
        if asset not in self.supported_assets():
            raise ValueError(f"unsupported asset: {asset.symbol}")
        return AssetMetadata(
            asset=asset,
            provider_symbol=asset.symbol,
            timezone="UTC",
            supported_intervals=self.supported_intervals(),
        )

    def corporate_actions(
        self, asset: Asset, start: datetime, end: datetime
    ) -> tuple[CorporateAction, ...]:
        """Return provider actions when supported; an empty tuple means unavailable/none."""
        del asset, start, end
        return ()

    def historical_batch(
        self,
        asset: Asset,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> HistoricalDataBatch:
        """Compatibility wrapper for deterministic providers without a raw transport payload."""
        bars = self.historical_data(asset, start, end, interval)
        raw = json.dumps(
            [bar.model_dump(mode="json") for bar in bars],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        metadata = self.provider_metadata()
        actions = self.corporate_actions(asset, start, end)
        return HistoricalDataBatch(
            provider=metadata.name,
            provider_version=metadata.version,
            asset=asset,
            interval=interval,
            requested_start=start,
            requested_end=end,
            fetched_at=datetime.now(UTC),
            bars=bars,
            corporate_actions=actions,
            raw_checksum=hashlib.sha256(raw).hexdigest(),
            diagnostics=DataQualityDiagnostics(input_rows=len(bars), output_rows=len(bars)),
            adjustment_policy=AdjustmentPolicy.SPLIT_ADJUSTED_WITH_CASH_DIVIDENDS,
            provider_configuration=metadata.configuration,
        )
