"""Backtest chronology, accounting, costs and regression tests."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from conftest import bars_from_closes

from app.backtesting import BacktestConfig, BacktestEngine, CostAssumptions, ExecutionModel
from app.backtesting.analytics import maximum_drawdown, recovery_time
from app.backtesting.models import SimulatedOrder
from app.data.synthetic import SyntheticMarketDataProvider
from app.models.enums import AssetClass, OrderSide, OrderType
from app.models.market import Asset, MarketBar
from app.models.strategy import StrategySpec
from app.strategies.base import Strategy
from app.strategies.reference import reference_strategies


class RuleStrategy(Strategy):
    def __init__(self, spec: StrategySpec, rule: str = "always") -> None:
        super().__init__(spec)
        self.rule = rule

    def desired_exposure(self, available_history: Sequence[MarketBar]) -> float:
        if self.rule == "round_trip":
            return 1.0 if len(available_history) < 3 else 0.0
        if self.rule == "threshold":
            return 1.0 if available_history[-1].close > 105 else 0.0
        return 1.0


def make_spec(asset: Asset) -> StrategySpec:
    return StrategySpec(
        strategy_id="test-rule",
        version=1,
        name="Test Rule",
        description="Test fixture",
        asset_class=asset.asset_class,
        permitted_assets=(asset.symbol,),
        timeframe="1d",
        indicators=(),
        entry_conditions=("fixture",),
        exit_conditions=("fixture",),
        parameters={},
    )


def zero_cost_config(*, fraction: float = 0.5) -> BacktestConfig:
    return BacktestConfig(
        starting_capital=1_000,
        position_fraction=fraction,
        costs=CostAssumptions(
            commission_bps=0,
            fixed_fee=0,
            minimum_commission=0,
            spread_bps=0,
            slippage_bps=0,
        ),
    )


def test_signal_fills_at_next_bar_open_not_same_bar(equity: Asset) -> None:
    bars = list(bars_from_closes(equity, [100, 110, 120]))
    bars[1] = bars[1].model_copy(update={"open": 105.0})
    strategy = RuleStrategy(make_spec(equity))
    result = BacktestEngine(zero_cost_config()).run(strategy, bars, dataset_id="test")
    assert result.fills[0].timestamp == bars[1].timestamp
    assert result.fills[0].timestamp > bars[0].timestamp
    assert result.fills[0].fill_price == 105.0


def test_execution_model_rejects_same_bar_fill(equity: Asset) -> None:
    bar = bars_from_closes(equity, [100])[0]
    order = SimulatedOrder(
        order_id="o1",
        strategy_version="test:v1",
        asset=equity,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1,
        decision_timestamp=bar.timestamp,
    )
    with pytest.raises(ValueError, match="same-bar"):
        ExecutionModel(CostAssumptions()).try_fill(order, bar)


def test_future_price_change_does_not_change_earlier_fill(equity: Asset) -> None:
    base = list(bars_from_closes(equity, [100, 110, 112, 115]))
    changed = [*base]
    changed[-1] = changed[-1].model_copy(
        update={"open": 1_000.0, "high": 1_010.0, "low": 114.0, "close": 1_000.0}
    )
    strategy = RuleStrategy(make_spec(equity), "threshold")
    engine = BacktestEngine(zero_cost_config())
    first = engine.run(strategy, base, dataset_id="base")
    second = engine.run(strategy, changed, dataset_id="changed")
    assert first.fills[0].timestamp == second.fills[0].timestamp == base[2].timestamp
    assert first.fills[0].fill_price == second.fills[0].fill_price


def test_round_trip_accounting_and_trade_attribution(equity: Asset) -> None:
    bars = bars_from_closes(equity, [100, 100, 110, 120, 120])
    strategy = RuleStrategy(make_spec(equity), "round_trip")
    result = BacktestEngine(zero_cost_config()).run(strategy, bars, dataset_id="accounting")
    assert len(result.trades) == 1
    assert result.trades[0].strategy_version == strategy.spec.version_key
    assert result.trades[0].net_pnl > 0
    for point in result.equity_curve:
        assert point.cash + point.market_value == pytest.approx(point.equity)


def test_fees_spread_and_slippage_reduce_performance(equity: Asset) -> None:
    bars = bars_from_closes(equity, [100, 100, 110, 120, 120])
    strategy = RuleStrategy(make_spec(equity), "round_trip")
    free = BacktestEngine(zero_cost_config()).run(strategy, bars, dataset_id="free")
    costly = BacktestEngine(
        BacktestConfig(
            starting_capital=1_000,
            position_fraction=0.5,
            costs=CostAssumptions(
                commission_bps=10,
                fixed_fee=1,
                minimum_commission=1,
                spread_bps=20,
                slippage_bps=15,
            ),
        )
    ).run(strategy, bars, dataset_id="costly")
    assert costly.final_equity < free.final_equity
    assert costly.metrics.fees_paid > 0
    assert costly.metrics.slippage_cost > 0


def test_limit_order_fill_and_non_fill(equity: Asset) -> None:
    timestamp = datetime(2024, 1, 2, 21, tzinfo=UTC)
    bar = MarketBar(
        timestamp=timestamp,
        open=100,
        high=105,
        low=95,
        close=102,
        volume=1_000,
        asset=equity,
        source="test",
        interval="1d",
    )
    model = ExecutionModel(zero_cost_config().costs)
    fillable = SimulatedOrder(
        order_id="limit-1",
        strategy_version="test:v1",
        asset=equity,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=2,
        limit_price=98,
        decision_timestamp=timestamp - timedelta(days=1),
    )
    missed = fillable.model_copy(update={"order_id": "limit-2", "limit_price": 90.0})
    fill = model.try_fill(fillable, bar)
    assert fill is not None and fill.fill_price <= 98
    assert model.try_fill(missed, bar) is None


def test_drawdown_and_open_recovery_are_measured() -> None:
    assert maximum_drawdown([100, 120, 90, 125]) == pytest.approx(0.25)
    assert recovery_time([100, 120, 90, 125]) == 2
    assert recovery_time([100, 120, 90, 110]) is None


@pytest.mark.regression
def test_reference_backtest_is_reproducible() -> None:
    provider = SyntheticMarketDataProvider(seed=1729)
    asset = next(
        item for item in provider.supported_assets() if item.asset_class is AssetClass.EQUITY
    )
    bars = provider.historical_data(
        asset,
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2021, 12, 31, 23, 59, tzinfo=UTC),
    )
    strategy = reference_strategies(asset.symbol)[0]
    engine = BacktestEngine()
    first = engine.run(strategy, bars, dataset_id="regression")
    second = engine.run(strategy, bars, dataset_id="regression")
    assert first == second
    assert first.metrics.number_of_trades == 6
    assert first.final_equity == pytest.approx(90_100.10877419572, rel=1e-12)
