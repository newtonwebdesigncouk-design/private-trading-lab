"""Multi-asset accounting, allocator, benchmark, and portfolio-risk tests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.data.models import CorporateAction
from app.models.enums import AdjustmentPolicy, AssetClass, CorporateActionType, OrderSide
from app.models.market import Asset, MarketBar
from app.models.strategy import StrategySpec
from app.portfolio import (
    EqualWeightAllocator,
    FixedWeightAllocator,
    PortfolioBacktestConfig,
    PortfolioBacktestEngine,
    ScoreWeightedAllocator,
    VolatilityAwareAllocator,
)
from app.risk import RiskContext, RiskEngine, RiskLimits, calculate_portfolio_risk_statistics
from app.strategies.base import Strategy
from app.universe import UniverseDefinition, UniverseInstrument


class TimedLongStrategy(Strategy):
    def desired_exposure(self, available_history: tuple[MarketBar, ...]) -> float:
        return 1.0 if 2 <= len(available_history) < 22 else 0.0


def market_bars(asset: Asset, *, multiplier: float = 1.0) -> tuple[MarketBar, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return tuple(
        MarketBar(
            timestamp=start + timedelta(days=index),
            open=(100 + index) * multiplier,
            high=(102 + index) * multiplier,
            low=(99 + index) * multiplier,
            close=(101 + index) * multiplier,
            adjusted_close=(101 + index) * multiplier,
            volume=1000,
            asset=asset,
            source="test",
            interval="1d",
        )
        for index in range(30)
    )


def strategy(asset: Asset) -> Strategy:
    return TimedLongStrategy(
        StrategySpec(
            strategy_id=f"timed-{asset.symbol.lower()}",
            version=1,
            name="Timed long",
            description="Test-only deterministic long window",
            asset_class=asset.asset_class,
            permitted_assets=(asset.symbol,),
            timeframe="1d",
            indicators=(),
            entry_conditions=("after warmup",),
            exit_conditions=("after fixed observation count",),
        )
    )


def universe(*assets: Asset) -> UniverseDefinition:
    return UniverseDefinition(
        universe_id="unit",
        version=1,
        provider="test",
        instruments=tuple(
            UniverseInstrument(
                asset=asset,
                category="test",
                inclusion_reason="deterministic acceptance fixture",
                benchmark_symbol=asset.symbol,
            )
            for asset in assets
        ),
    )


def permissive_risk() -> RiskEngine:
    return RiskEngine(
        RiskLimits(
            maximum_position_percentage=0.40,
            maximum_asset_class_exposure=0.80,
            maximum_portfolio_exposure=0.80,
            minimum_cash_reserve=0.10,
            maximum_concurrent_positions=5,
            maximum_trades_per_period=1000,
            maximum_turnover_per_period=100,
            maximum_correlated_exposure=1,
            stale_after=timedelta(days=2),
        )
    )


def test_multi_asset_portfolio_is_cash_funded_attributed_and_benchmarked() -> None:
    spy = Asset(symbol="SPY", asset_class=AssetClass.ETF, exchange="TEST")
    btc = Asset(symbol="BTCUSD", asset_class=AssetClass.CRYPTOCURRENCY, exchange="TEST")
    result = PortfolioBacktestEngine(
        PortfolioBacktestConfig(starting_capital=10_000, rebalance_threshold=0.02),
        risk_engine=permissive_risk(),
    ).run(
        {spy.symbol: strategy(spy), btc.symbol: strategy(btc)},
        {spy.symbol: market_bars(spy), btc.symbol: market_bars(btc, multiplier=2)},
        dataset_id="portfolio-unit-v1",
        universe=universe(spy, btc),
    )
    assert result.equity_curve
    assert all(point.cash >= 0 for point in result.equity_curve)
    # Market moves can drift above a target cap between rebalances, but never create leverage.
    assert all(sum(point.position_weights.values()) <= 1.0 + 1e-7 for point in result.equity_curve)
    assert any(len(point.position_values) == 2 for point in result.equity_curve)
    assert result.metrics.fees_paid > 0
    assert result.metrics.turnover > 0
    assert {item.benchmark for item in result.benchmarks} == {
        "BUY_HOLD_SPY",
        "BUY_HOLD_BTCUSD",
        "EQUAL_WEIGHT_UNIVERSE",
        "CASH_BASELINE",
    }
    assert {item.key for item in result.asset_attribution} == {"SPY", "BTCUSD"}
    assert {item.key for item in result.asset_class_attribution} == {
        "ETF",
        "CRYPTOCURRENCY",
    }
    assert result.strategy_attribution


def test_unadjusted_split_changes_quantity_without_creating_leverage() -> None:
    asset = Asset(symbol="SPLIT", asset_class=AssetClass.EQUITY, exchange="TEST")
    bars = list(market_bars(asset))
    split_timestamp = bars[4].timestamp
    for index in range(4, len(bars)):
        bars[index] = bars[index].model_copy(
            update={
                "open": bars[index].open / 2,
                "high": bars[index].high / 2,
                "low": bars[index].low / 2,
                "close": bars[index].close / 2,
                "adjusted_close": None,
            }
        )
    action = CorporateAction(
        asset=asset,
        effective_timestamp=split_timestamp,
        action_type=CorporateActionType.STOCK_SPLIT,
        split_ratio=2,
        source="test",
    )
    result = PortfolioBacktestEngine(
        PortfolioBacktestConfig(starting_capital=10_000, rebalance_threshold=0.05),
        risk_engine=permissive_risk(),
    ).run(
        {asset.symbol: strategy(asset)},
        {asset.symbol: tuple(bars)},
        dataset_id="split-v1",
        universe=universe(asset),
        corporate_actions={asset.symbol: (action,)},
        adjustment_policy=AdjustmentPolicy.UNADJUSTED_WITH_ACTIONS,
    )
    assert all(point.cash >= 0 for point in result.equity_curve)
    assert result.adjustment_policy is AdjustmentPolicy.UNADJUSTED_WITH_ACTIONS
    assert result.fills
    assert result.equity_curve[4].equity / result.equity_curve[3].equity > 0.80


def test_allocation_catalogue_is_deterministic_and_strictly_bounded() -> None:
    symbols = ("A", "B", "C", "D", "E")
    equal = EqualWeightAllocator(maximum_position_weight=0.15, maximum_total_weight=0.60).allocate(
        symbols
    )
    assert sum(equal.weights.values()) == pytest.approx(0.60)
    assert max(equal.weights.values()) <= 0.15
    assert equal.cash_weight == pytest.approx(0.40)
    fixed = FixedWeightAllocator(
        {"A": 0.8, "B": 0.2},
        maximum_position_weight=0.30,
        maximum_total_weight=0.50,
    ).allocate(("A", "B"))
    assert fixed.weights == {"A": pytest.approx(0.30), "B": pytest.approx(0.20)}
    volatility = VolatilityAwareAllocator(
        maximum_position_weight=0.8, maximum_total_weight=0.8
    ).allocate(("A", "B"), volatilities={"A": 0.1, "B": 0.4})
    assert volatility.weights["A"] > volatility.weights["B"]
    scored = ScoreWeightedAllocator(maximum_position_weight=0.8, maximum_total_weight=0.8).allocate(
        ("A", "B"), scores={"A": 80, "B": 20}
    )
    assert scored.weights["A"] > scored.weights["B"]
    with pytest.raises(ValueError, match="negative"):
        FixedWeightAllocator({"A": -0.1})
    with pytest.raises(ValueError, match="caps"):
        EqualWeightAllocator(maximum_position_weight=2).allocate(("A",))


def test_portfolio_risk_controls_and_correlation_statistics_dominate_requests() -> None:
    limits = RiskLimits(
        minimum_cash_reserve=0.10,
        maximum_turnover_per_period=0.50,
        maximum_correlated_exposure=0.30,
        stale_after=timedelta(hours=1),
    )
    engine = RiskEngine(limits)
    now = datetime(2024, 1, 2, tzinfo=UTC)
    context = RiskContext(
        portfolio_equity=1000,
        current_portfolio_exposure=0.20,
        current_asset_class_exposure={AssetClass.EQUITY: 0.20},
        open_position_symbols=frozenset({"OTHER"}),
        market_timestamp=now - timedelta(hours=2),
        evaluation_timestamp=now,
        previous_price=100,
        cash_available=150,
        current_turnover=0.45,
        current_position_weights={"OTHER": 0.20},
        correlated_exposure=0.25,
    )
    decision = engine.evaluate(
        symbol="NEW",
        asset_class=AssetClass.EQUITY,
        side=OrderSide.BUY,
        requested_notional=100,
        requested_price=130,
        context=context,
    )
    assert not decision.allowed
    assert set(decision.reasons) >= {
        "market data is stale",
        "abnormal price movement",
        "minimum cash reserve would be breached",
        "maximum turnover exceeded",
        "correlation-aware concentration limit exceeded",
    }
    statistics = calculate_portfolio_risk_statistics(
        {"A": (0.01, 0.02, -0.01), "B": (0.02, 0.04, -0.02)},
        {"A": 0.4, "B": 0.4},
    )
    assert statistics.correlation_matrix["A"]["B"] == pytest.approx(1.0)
    assert statistics.portfolio_volatility > 0
    assert sum(statistics.risk_contribution.values()) == pytest.approx(1.0)
    empty = calculate_portfolio_risk_statistics({}, {})
    assert empty.portfolio_volatility == 0
