"""Phase 2 provider, normalisation, action-policy, and snapshot acceptance tests."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.data.calendar import expected_daily_close_timestamps
from app.data.corporate_actions import apply_adjustment_policy, split_ratio_at
from app.data.models import CorporateAction, RawMarketBar
from app.data.normalization import normalise_bars
from app.data.providers.stooq import StooqReadOnlyProvider
from app.data.providers.transport import ProviderTransportError
from app.data.providers.yahoo import YahooReadOnlyProvider
from app.data.snapshots import DatasetSnapshotStore
from app.models.enums import AdjustmentPolicy, AssetClass, CorporateActionType
from app.models.market import Asset, MarketBar


class FakeTransport:
    def __init__(self, outcomes: list[bytes | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def get(self, url: str, *, timeout_seconds: float) -> bytes:
        self.calls.append(f"{url}|{timeout_seconds}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def yahoo_payload() -> bytes:
    return json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "timestamp": [1704067200, 1704153600],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0, 102.0],
                                    "high": [103.0, 105.0],
                                    "low": [99.0, 101.0],
                                    "close": [102.0, 104.0],
                                    "volume": [1000, 1200],
                                }
                            ],
                            "adjclose": [{"adjclose": [101.0, 104.0]}],
                        },
                        "events": {
                            "dividends": {"x": {"date": 1704067200, "amount": 0.5}},
                            "splits": {
                                "y": {
                                    "date": 1704153600,
                                    "numerator": 2,
                                    "denominator": 1,
                                    "splitRatio": "2:1",
                                }
                            },
                        },
                    }
                ],
            }
        }
    ).encode()


def test_yahoo_provider_is_get_only_retries_and_normalises_actions() -> None:
    asset = Asset(symbol="TEST", asset_class=AssetClass.ETF, exchange="YAHOO")
    transport = FakeTransport(
        [
            ProviderTransportError("rate limited", status_code=429),
            yahoo_payload(),
            yahoo_payload(),
            yahoo_payload(),
        ]
    )
    sleeps: list[float] = []
    provider = YahooReadOnlyProvider(
        {asset: "TEST"}, transport=transport, sleeper=sleeps.append, retry_delay_seconds=0.1
    )
    batch = provider.historical_batch(
        asset,
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 4, tzinfo=UTC),
    )
    assert len(transport.calls) == 2
    assert sleeps == [0.1]
    assert len(batch.bars) == 2
    assert batch.bars[0].timestamp == datetime(2024, 1, 2, tzinfo=UTC)
    assert batch.bars[0].close == pytest.approx(101.0)
    assert batch.adjustment_policy is AdjustmentPolicy.TOTAL_RETURN_ADJUSTED
    assert {action.action_type for action in batch.corporate_actions} == {
        CorporateActionType.CASH_DIVIDEND,
        CorporateActionType.STOCK_SPLIT,
    }
    assert provider.latest_price(asset, datetime(2024, 1, 4, tzinfo=UTC)).close == 104
    assert provider.corporate_actions(
        asset, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 4, tzinfo=UTC)
    )
    assert provider.provider_metadata().capabilities.read_only
    assert not provider.provider_metadata().capabilities.requires_secret
    with pytest.raises(ValueError, match="daily bars"):
        provider.historical_data(
            asset,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 4, tzinfo=UTC),
            "1h",
        )


def test_provider_errors_and_partial_rows_are_explicit() -> None:
    asset = Asset(symbol="TEST", asset_class=AssetClass.ETF, exchange="YAHOO")
    failing = YahooReadOnlyProvider(
        {asset: "TEST"},
        transport=FakeTransport([ProviderTransportError("bad", status_code=403)]),
    )
    with pytest.raises(ProviderTransportError):
        failing.historical_data(
            asset,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 4, tzinfo=UTC),
        )
    malformed = FakeTransport([b'{"chart":{"error":null,"result":[]}}'])
    empty = YahooReadOnlyProvider({asset: "TEST"}, transport=malformed).historical_batch(
        asset,
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 4, tzinfo=UTC),
    )
    assert empty.diagnostics.partial_response
    assert "no usable bars" in empty.diagnostics.warnings[-1]
    with pytest.raises(ValueError, match="configured"):
        failing.asset_metadata(Asset(symbol="OTHER", asset_class=AssetClass.ETF, exchange="YAHOO"))


def test_stooq_html_or_invalid_payload_is_reported_not_silently_accepted() -> None:
    asset = Asset(symbol="TEST", asset_class=AssetClass.ETF, exchange="STOOQ")
    provider = StooqReadOnlyProvider(
        {asset: "test.us"}, transport=FakeTransport([b"<html>challenge</html>"])
    )
    batch = provider.historical_batch(
        asset,
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 4, tzinfo=UTC),
    )
    assert not batch.bars
    assert batch.diagnostics.invalid_rows == 1
    assert batch.diagnostics.partial_response


def test_normalisation_reports_duplicates_order_invalid_rows_missing_and_dst() -> None:
    asset = Asset(symbol="TEST", asset_class=AssetClass.EQUITY, exchange="TEST")
    first = datetime(2024, 3, 10, 1, 30)
    second = datetime(2024, 3, 10, 3, 30)
    rows = (
        RawMarketBar(timestamp=second, open=101, high=103, low=100, close=102),
        RawMarketBar(timestamp=first, open=100, high=102, low=99, close=101),
        RawMarketBar(timestamp=first, open=100, high=102, low=99, close=101),
        RawMarketBar(timestamp=datetime(2024, 3, 11), open=-1, high=-1, low=-1, close=-1),
    )
    expected_missing = datetime(2024, 3, 12, tzinfo=UTC)
    bars, diagnostics = normalise_bars(
        rows,
        asset=asset,
        source="test",
        interval="1h",
        source_timezone="America/New_York",
        expected_timestamps=(expected_missing,),
    )
    assert [bar.timestamp.hour for bar in bars] == [6, 7]
    assert diagnostics.duplicate_rows == 1
    assert diagnostics.out_of_order_rows == 1
    assert diagnostics.invalid_rows == 1
    assert diagnostics.missing_expected_timestamps == (expected_missing,)
    assert {event.event_type for event in diagnostics.events} >= {
        "TIMEZONE_ATTACHED",
        "DUPLICATE_ROW_REJECTED",
        "INVALID_ROW_REJECTED",
        "ROWS_SORTED",
    }


def test_snapshot_is_content_addressed_immutable_and_checksum_verified(tmp_path: Path) -> None:
    root = tmp_path
    asset = Asset(symbol="TEST", asset_class=AssetClass.ETF, exchange="YAHOO")
    provider = YahooReadOnlyProvider({asset: "TEST"}, transport=FakeTransport([yahoo_payload()]))
    batch = provider.historical_batch(
        asset,
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 4, tzinfo=UTC),
    )
    store = DatasetSnapshotStore(root)
    manifest = store.freeze(
        "unit",
        (batch,),
        code_revision="abc123",
        corporate_action_policy="total return adjusted; actions retained as metadata",
    )
    repeated = store.freeze(
        "unit",
        (batch.model_copy(update={"fetched_at": datetime.now(UTC)}),),
        code_revision="different-does-not-rewrite-content",
        corporate_action_policy="total return adjusted; actions retained as metadata",
    )
    assert repeated == manifest
    assert store.validate(manifest.dataset_id) == ()
    assert store.load_bars(manifest.dataset_id, "TEST") == batch.bars
    assert len(store.load_actions(manifest.dataset_id, "TEST")) == 2
    assert store.list_manifests() == (manifest,)
    freshness = store.freshness(
        manifest.dataset_id,
        as_of=manifest.actual_end + timedelta(days=2),
        maximum_age=timedelta(days=1),
    )
    assert freshness.stale
    with pytest.raises(ValueError, match="positive"):
        store.freshness(
            manifest.dataset_id,
            as_of=manifest.actual_end,
            maximum_age=timedelta(0),
        )
    artifact = root / manifest.dataset_id / manifest.instruments[0].artifact
    artifact.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        store.load_bars(manifest.dataset_id, "TEST")


def test_corporate_action_policies_prevent_dividend_double_counting(equity: Asset) -> None:
    timestamp = datetime(2024, 1, 2, tzinfo=UTC)
    bar = MarketBar(
        timestamp=timestamp,
        open=50,
        high=51,
        low=49,
        close=50,
        adjusted_close=50.5,
        volume=100,
        asset=equity,
        source="test",
        interval="1d",
    )
    dividend = CorporateAction(
        asset=equity,
        effective_timestamp=timestamp,
        action_type=CorporateActionType.CASH_DIVIDEND,
        cash_amount=0.5,
        source="test",
    )
    split = CorporateAction(
        asset=equity,
        effective_timestamp=timestamp,
        action_type=CorporateActionType.STOCK_SPLIT,
        split_ratio=2,
        source="test",
    )
    raw = apply_adjustment_policy(
        (bar,), (dividend, split), AdjustmentPolicy.UNADJUSTED_WITH_ACTIONS
    )
    adjusted = apply_adjustment_policy(
        (bar,), (dividend, split), AdjustmentPolicy.TOTAL_RETURN_ADJUSTED
    )
    assert raw[0].dividend == 0.5
    assert adjusted[0].dividend == 0
    assert split_ratio_at((split,), bar) == 2
    no_adjusted = bar.model_copy(update={"adjusted_close": None})
    with pytest.raises(ValueError, match="requires adjusted_close"):
        apply_adjustment_policy((no_adjusted,), (), AdjustmentPolicy.TOTAL_RETURN_ADJUSTED)


def test_expected_calendars_handle_weekends_holidays_and_continuous_crypto() -> None:
    holiday = date(2024, 1, 1)
    equity_dates = expected_daily_close_timestamps(
        date(2024, 1, 1),
        date(2024, 1, 7),
        asset_class=AssetClass.EQUITY,
        holidays=(holiday,),
    )
    crypto_dates = expected_daily_close_timestamps(
        date(2024, 1, 1), date(2024, 1, 7), asset_class=AssetClass.CRYPTOCURRENCY
    )
    assert len(equity_dates) == 4
    assert len(crypto_dates) == 7
    with pytest.raises(ValueError, match="start"):
        expected_daily_close_timestamps(
            date(2024, 1, 2), date(2024, 1, 1), asset_class=AssetClass.EQUITY
        )
