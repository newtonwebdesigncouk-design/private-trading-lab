"""Long-only, deterministic, next-bar-open simulation engine."""

import hashlib
from collections.abc import Sequence

from app.backtesting.analytics import calculate_metrics
from app.backtesting.models import (
    BacktestConfig,
    BacktestResult,
    CostAssumptions,
    EquityPoint,
    SimulatedFill,
    SimulatedOrder,
    Trade,
)
from app.benchmarks import compare_with_buy_and_hold
from app.models.enums import OrderSide, OrderType
from app.models.market import MarketBar
from app.strategies.base import Strategy


class ExecutionModel:
    """Simulates fills locally. It has no network, account, or external-order capability."""

    def __init__(self, costs: CostAssumptions) -> None:
        self.costs = costs

    def commission(self, notional: float) -> float:
        variable = notional * self.costs.commission_bps / 10_000
        return max(self.costs.minimum_commission, self.costs.fixed_fee + variable)

    def try_fill(self, order: SimulatedOrder, bar: MarketBar) -> SimulatedFill | None:
        if bar.timestamp <= order.decision_timestamp:
            raise ValueError("same-bar or backwards execution is forbidden")
        half_spread = self.costs.spread_bps / 20_000
        slippage = self.costs.slippage_bps / 10_000
        if order.order_type is OrderType.MARKET:
            reference = bar.open
            multiplier = (
                1 + half_spread + slippage
                if order.side is OrderSide.BUY
                else 1 - half_spread - slippage
            )
            fill_price = reference * multiplier
        else:
            if order.limit_price is None:
                raise ValueError("limit price is required")
            if order.side is OrderSide.BUY:
                if bar.low > order.limit_price:
                    return None
                reference = min(bar.open, order.limit_price)
                fill_price = min(order.limit_price, reference * (1 + half_spread + slippage))
            else:
                if bar.high < order.limit_price:
                    return None
                reference = max(bar.open, order.limit_price)
                fill_price = max(order.limit_price, reference * (1 - half_spread - slippage))
        notional = order.quantity * fill_price
        return SimulatedFill(
            order_id=order.order_id,
            timestamp=bar.timestamp,
            side=order.side,
            quantity=order.quantity,
            reference_price=reference,
            fill_price=fill_price,
            notional=notional,
            fee=self.commission(notional),
            slippage_cost=order.quantity * reference * slippage,
        )


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self.execution = ExecutionModel(self.config.costs)

    @staticmethod
    def _validate_bars(strategy: Strategy, bars: Sequence[MarketBar]) -> None:
        if len(bars) < 2:
            raise ValueError("at least two bars are required")
        if any(
            bars[index].timestamp >= bars[index + 1].timestamp for index in range(len(bars) - 1)
        ):
            raise ValueError("bars must have unique, ascending timestamps")
        asset = bars[0].asset
        if any(bar.asset != asset for bar in bars):
            raise ValueError("a backtest currently accepts one canonical asset")
        if asset.symbol not in strategy.spec.permitted_assets:
            raise ValueError("asset is not permitted by the strategy specification")
        if asset.asset_class is not strategy.spec.asset_class:
            raise ValueError("strategy and market-data asset classes differ")

    @staticmethod
    def _order_id(strategy: Strategy, side: OrderSide, timestamp: object, index: int) -> str:
        raw = f"{strategy.spec.version_key}|{side}|{timestamp}|{index}".encode()
        return hashlib.sha256(raw).hexdigest()[:20]

    def run(
        self, strategy: Strategy, bars: Sequence[MarketBar], *, dataset_id: str
    ) -> BacktestResult:
        self._validate_bars(strategy, bars)
        cash = self.config.starting_capital
        quantity = 0.0
        entry_price = 0.0
        entry_time = bars[0].timestamp
        entry_fees = 0.0
        realised_pnl = 0.0
        peak_equity = cash
        pending: SimulatedOrder | None = None
        fills: list[SimulatedFill] = []
        trades: list[Trade] = []
        curve: list[EquityPoint] = []

        for index, bar in enumerate(bars):
            if quantity > 0 and bar.dividend:
                cash += quantity * bar.dividend

            if pending is not None:
                fill = self.execution.try_fill(pending, bar)
                if fill is not None:
                    if fill.side is OrderSide.BUY:
                        total_cost = fill.notional + fill.fee
                        if total_cost <= cash + 1e-7:
                            cash -= total_cost
                            quantity = fill.quantity
                            entry_price = fill.fill_price
                            entry_time = fill.timestamp
                            entry_fees = fill.fee
                            fills.append(fill)
                    elif quantity > 0:
                        sold_quantity = min(quantity, fill.quantity)
                        proceeds = sold_quantity * fill.fill_price - fill.fee
                        cash += proceeds
                        gross_pnl = sold_quantity * (fill.fill_price - entry_price)
                        net_pnl = gross_pnl - entry_fees - fill.fee
                        realised_pnl += net_pnl
                        trades.append(
                            Trade(
                                asset=bar.asset.symbol,
                                strategy_version=strategy.spec.version_key,
                                entry_timestamp=entry_time,
                                exit_timestamp=fill.timestamp,
                                quantity=sold_quantity,
                                entry_price=entry_price,
                                exit_price=fill.fill_price,
                                gross_pnl=gross_pnl,
                                net_pnl=net_pnl,
                                fees=entry_fees + fill.fee,
                            )
                        )
                        fills.append(fill)
                        quantity = 0.0
                        entry_price = 0.0
                        entry_fees = 0.0
                pending = None

            market_value = quantity * bar.effective_close
            equity = cash + market_value
            peak_equity = max(peak_equity, equity)
            unrealised = (
                quantity * (bar.effective_close - entry_price) - entry_fees if quantity else 0.0
            )
            curve.append(
                EquityPoint(
                    timestamp=bar.timestamp,
                    cash=cash,
                    position_quantity=quantity,
                    market_value=market_value,
                    equity=equity,
                    realised_pnl=realised_pnl,
                    unrealised_pnl=unrealised,
                    drawdown=equity / peak_equity - 1.0,
                )
            )

            if index == len(bars) - 1:
                continue
            target = strategy.desired_exposure(tuple(bars[: index + 1]))
            if not 0.0 <= target <= 1.0:
                raise ValueError("strategy requested exposure outside [0, 1]")
            if quantity == 0 and target > 0:
                budget = equity * min(target, self.config.position_fraction)
                estimated_price = bar.effective_close * (
                    1
                    + self.config.costs.spread_bps / 20_000
                    + self.config.costs.slippage_bps / 10_000
                )
                estimated_fee = self.execution.commission(budget)
                order_quantity = max(0.0, min(budget, cash - estimated_fee) / estimated_price)
                if order_quantity > 0:
                    pending = SimulatedOrder(
                        order_id=self._order_id(strategy, OrderSide.BUY, bar.timestamp, index),
                        strategy_version=strategy.spec.version_key,
                        asset=bar.asset,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=order_quantity,
                        decision_timestamp=bar.timestamp,
                    )
            elif quantity > 0 and target == 0:
                pending = SimulatedOrder(
                    order_id=self._order_id(strategy, OrderSide.SELL, bar.timestamp, index),
                    strategy_version=strategy.spec.version_key,
                    asset=bar.asset,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=quantity,
                    decision_timestamp=bar.timestamp,
                )

        metrics = calculate_metrics(curve, trades, fills, self.config.annual_periods)
        benchmark = compare_with_buy_and_hold(metrics, bars, self.config.annual_periods)
        return BacktestResult(
            strategy=strategy.spec,
            dataset_id=dataset_id,
            start=bars[0].timestamp,
            end=bars[-1].timestamp,
            starting_capital=self.config.starting_capital,
            final_equity=curve[-1].equity,
            costs=self.config.costs,
            metrics=metrics,
            benchmark=benchmark,
            fills=tuple(fills),
            trades=tuple(trades),
            equity_curve=tuple(curve),
        )
