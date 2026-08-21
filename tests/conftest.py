"""Shared deterministic fixtures."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import AssetClass
from app.models.market import Asset, MarketBar


@pytest.fixture
def equity() -> Asset:
    return Asset(symbol="TEST", asset_class=AssetClass.EQUITY, exchange="TEST")


def bars_from_closes(asset: Asset, closes: list[float]) -> tuple[MarketBar, ...]:
    start = datetime(2024, 1, 1, 21, tzinfo=UTC)
    return tuple(
        MarketBar(
            timestamp=start + timedelta(days=index),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            adjusted_close=close,
            volume=1_000,
            asset=asset,
            source="test",
            interval="1d",
        )
        for index, close in enumerate(closes)
    )
