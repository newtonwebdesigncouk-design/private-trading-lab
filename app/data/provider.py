"""Provider-neutral market data contract."""

from abc import ABC, abstractmethod
from datetime import datetime

from app.models.market import Asset, MarketBar


class MarketDataProvider(ABC):
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
