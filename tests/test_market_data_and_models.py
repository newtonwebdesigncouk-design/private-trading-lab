"""Canonical data, cache and immutable strategy tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.data.synthetic import SyntheticMarketDataProvider
from app.models.enums import AssetClass
from app.models.market import Asset, MarketBar
from app.strategies.reference import reference_strategies


def test_all_required_asset_classes_are_modelled() -> None:
    assert {item.value for item in AssetClass} == {
        "EQUITY",
        "ETF",
        "CRYPTOCURRENCY",
        "FOREX",
        "INDEX",
    }


def test_market_bar_rejects_inconsistent_ohlc(equity: Asset) -> None:
    with pytest.raises(ValidationError):
        MarketBar(
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            open=100,
            high=99,
            low=98,
            close=100,
            volume=1,
            asset=equity,
            source="test",
            interval="1d",
        )


def test_market_bar_requires_timezone(equity: Asset) -> None:
    with pytest.raises(ValidationError):
        MarketBar(
            timestamp=datetime(2024, 1, 1),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
            asset=equity,
            source="test",
            interval="1d",
        )


def test_synthetic_provider_is_deterministic_and_cacheable(tmp_path: Path) -> None:
    provider = SyntheticMarketDataProvider(seed=42, cache_dir=tmp_path)
    asset = provider.supported_assets()[0]
    start = datetime(2023, 1, 1, tzinfo=UTC)
    end = datetime(2023, 4, 1, tzinfo=UTC)
    first = provider.historical_data(asset, start, end)
    second = provider.historical_data(asset, start, end)
    uncached = SyntheticMarketDataProvider(seed=42).historical_data(asset, start, end)
    assert first == second == uncached
    assert list(tmp_path.rglob("*.json"))


def test_synthetic_provider_changes_with_seed() -> None:
    first_provider = SyntheticMarketDataProvider(seed=1)
    asset = first_provider.supported_assets()[0]
    start = datetime(2023, 1, 1, tzinfo=UTC)
    end = datetime(2023, 2, 1, tzinfo=UTC)
    first = first_provider.historical_data(asset, start, end)
    second = SyntheticMarketDataProvider(seed=2).historical_data(asset, start, end)
    assert [bar.close for bar in first] != [bar.close for bar in second]


def test_overlapping_synthetic_requests_return_identical_canonical_bars() -> None:
    provider = SyntheticMarketDataProvider(seed=42)
    asset = provider.supported_assets()[0]
    full = provider.historical_data(
        asset,
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2023, 4, 1, tzinfo=UTC),
    )
    overlap = provider.historical_data(
        asset,
        datetime(2023, 3, 1, tzinfo=UTC),
        datetime(2023, 4, 1, tzinfo=UTC),
    )
    expected = tuple(bar for bar in full if bar.timestamp >= datetime(2023, 3, 1, tzinfo=UTC))
    assert overlap == expected


def test_strategy_spec_is_frozen_and_derivation_versions_it() -> None:
    original = reference_strategies()[0].spec
    with pytest.raises(TypeError):
        original.parameters["fast_window"] = 99  # type: ignore[index]
    derived = original.derive(
        parameters={**original.parameters, "fast_window": 21}, reason="nearby parameter"
    )
    assert original.version == 1
    assert derived.version == 2
    assert derived.parent_strategy == original.version_key
    assert derived.parameters["fast_window"] == 21
