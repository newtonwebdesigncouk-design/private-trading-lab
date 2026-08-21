"""Deterministic long-only, cash-funded multi-asset portfolio simulation."""

import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting.analytics import (
    annualised_volatility,
    maximum_drawdown,
    periodic_returns,
    recovery_time,
    sharpe_ratio,
    sortino_ratio,
)
from app.backtesting.engine import ExecutionModel
from app.backtesting.models import CostAssumptions, SimulatedFill, SimulatedOrder, Trade
from app.benchmarks.portfolio import calculate_portfolio_benchmarks
from app.data.corporate_actions import split_ratio_at
from app.data.models import CorporateAction
from app.models.enums import AdjustmentPolicy, AssetClass, OrderSide, OrderType
from app.models.market import MarketBar
from app.portfolio.allocation import EqualWeightAllocator, PortfolioAllocator
from app.portfolio.models import (
    PortfolioAttribution,
    PortfolioBacktestResult,
    PortfolioEquityPoint,
    PortfolioMetrics,
    PortfolioPosition,
    RejectedPortfolioOrder,
)
from app.risk import RiskContext, RiskEngine, RiskLimits, calculate_portfolio_risk_statistics
from app.strategies.base import Strategy
from app.universe import UniverseDefinition


class PortfolioBacktestConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    starting_capital: float = Field(default=100_000.0, gt=0)
    annual_periods: int = Field(default=252, gt=0)
    rebalance_threshold: float = Field(default=0.005, ge=0, le=1)
    costs: CostAssumptions = Field(default_factory=CostAssumptions)


def _portfolio_metrics(
    curve: Sequence[PortfolioEquityPoint],
    fills: Sequence[SimulatedFill],
    trades: Sequence[Trade],
    annual_periods: int,
) -> PortfolioMetrics:
    values = [point.equity for point in curve]
    returns = periodic_returns(values)
    downside = [min(value, 0.0) for value in returns]
    years = max((len(values) - 1) / annual_periods, 1.0 / annual_periods)
    total_return = values[-1] / values[0] - 1.0
    return PortfolioMetrics(
        total_return=total_return,
        annualised_return=(values[-1] / values[0]) ** (1 / years) - 1,
        volatility=annualised_volatility(returns, annual_periods),
        sharpe_ratio=sharpe_ratio(returns, annual_periods),
        sortino_ratio=sortino_ratio(returns, annual_periods),
        downside_risk=(
            math.sqrt(sum(value * value for value in downside) / len(downside))
            * math.sqrt(annual_periods)
            if downside
            else 0.0
        ),
        maximum_drawdown=maximum_drawdown(values),
        recovery_time_bars=recovery_time(values),
        turnover=sum(fill.notional for fill in fills) / (sum(values) / len(values)),
        average_invested_exposure=sum(point.market_value / point.equity for point in curve)
        / len(curve),
        average_cash_exposure=sum(point.cash / point.equity for point in curve) / len(curve),
        fees_paid=sum(fill.fee for fill in fills),
        slippage_cost=sum(fill.slippage_cost for fill in fills),
        number_of_trades=len(trades),
    )


class PortfolioBacktestEngine:
    """One strategy per asset, synchronized at common timestamps, with next-bar fills."""

    def __init__(
        self,
        config: PortfolioBacktestConfig | None = None,
        *,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.config = config or PortfolioBacktestConfig()
        self.execution = ExecutionModel(self.config.costs)
        self.risk = risk_engine or RiskEngine(
            RiskLimits(
                maximum_position_percentage=0.25,
                maximum_asset_class_exposure=0.75,
                maximum_portfolio_exposure=0.90,
                maximum_concurrent_positions=8,
                stale_after=datetime.max - datetime.min,
            )
        )

    @staticmethod
    def _validate(
        strategies: Mapping[str, Strategy],
        bars_by_symbol: Mapping[str, Sequence[MarketBar]],
        universe: UniverseDefinition,
    ) -> tuple[datetime, ...]:
        if not strategies or set(strategies) != set(bars_by_symbol):
            raise ValueError("strategies and bar series must have identical non-empty symbols")
        universe_symbols = {asset.symbol for asset in universe.assets}
        if not set(strategies).issubset(universe_symbols):
            raise ValueError("all strategies must belong to the versioned universe")
        common: set[datetime] | None = None
        for symbol, bars in bars_by_symbol.items():
            if len(bars) < 2:
                raise ValueError(f"at least two bars are required for {symbol}")
            if any(
                bars[index].timestamp >= bars[index + 1].timestamp for index in range(len(bars) - 1)
            ):
                raise ValueError(f"bars must be uniquely ascending for {symbol}")
            if any(bar.asset.symbol != symbol for bar in bars):
                raise ValueError(f"bar symbol mismatch for {symbol}")
            strategy = strategies[symbol]
            if symbol not in strategy.spec.permitted_assets:
                raise ValueError(f"strategy does not permit {symbol}")
            if bars[0].asset.asset_class is not strategy.spec.asset_class:
                raise ValueError(f"strategy asset class differs for {symbol}")
            timestamps = {bar.timestamp for bar in bars}
            common = timestamps if common is None else common.intersection(timestamps)
        timeline = tuple(sorted(common or ()))
        if len(timeline) < 2:
            raise ValueError("multi-asset portfolio requires at least two common timestamps")
        return timeline

    @staticmethod
    def _order_id(
        dataset_id: str, strategy: Strategy, symbol: str, side: OrderSide, timestamp: datetime
    ) -> str:
        raw = f"{dataset_id}|{strategy.spec.version_key}|{symbol}|{side}|{timestamp}".encode()
        return hashlib.sha256(raw).hexdigest()[:24]

    def run(
        self,
        strategies: Mapping[str, Strategy],
        bars_by_symbol: Mapping[str, Sequence[MarketBar]],
        *,
        dataset_id: str,
        universe: UniverseDefinition,
        allocator: PortfolioAllocator | None = None,
        scores: Mapping[str, float] | None = None,
        corporate_actions: Mapping[str, Sequence[CorporateAction]] | None = None,
        adjustment_policy: AdjustmentPolicy = AdjustmentPolicy.SPLIT_ADJUSTED_WITH_CASH_DIVIDENDS,
    ) -> PortfolioBacktestResult:
        timeline = self._validate(strategies, bars_by_symbol, universe)
        bar_maps = {
            symbol: {bar.timestamp: bar for bar in bars} for symbol, bars in bars_by_symbol.items()
        }
        histories: dict[str, list[MarketBar]] = {symbol: [] for symbol in strategies}
        allocator = allocator or EqualWeightAllocator(
            maximum_position_weight=self.risk.limits.maximum_position_percentage,
            maximum_total_weight=self.risk.limits.maximum_portfolio_exposure,
        )
        actions = corporate_actions or {}
        cash = self.config.starting_capital
        realised_pnl = 0.0
        positions: dict[str, PortfolioPosition] = {}
        pending: dict[str, SimulatedOrder] = {}
        latest_prices: dict[str, float] = {}
        fills: list[SimulatedFill] = []
        rejected: list[RejectedPortfolioOrder] = []
        trades: list[Trade] = []
        curve: list[PortfolioEquityPoint] = []
        peak = cash
        turnover_notional = 0.0

        for timeline_index, timestamp in enumerate(timeline):
            current_bars = {symbol: bar_maps[symbol][timestamp] for symbol in strategies}
            for symbol in sorted(current_bars):
                bar = current_bars[symbol]
                position = positions.get(symbol)
                if position is not None:
                    ratio = split_ratio_at(actions.get(symbol, ()), bar)
                    if ratio != 1 and adjustment_policy is AdjustmentPolicy.UNADJUSTED_WITH_ACTIONS:
                        position = position.model_copy(
                            update={
                                "quantity": position.quantity * ratio,
                                "average_price": position.average_price / ratio,
                            }
                        )
                        positions[symbol] = position
                    if bar.dividend:
                        cash += position.quantity * bar.dividend

            ordered_pending = sorted(
                pending.values(),
                key=lambda order: (order.side is OrderSide.BUY, order.asset.symbol),
            )
            for order in ordered_pending:
                symbol = order.asset.symbol
                bar = current_bars[symbol]
                fill = self.execution.try_fill(order, bar)
                if fill is None:
                    continue
                position = positions.get(symbol)
                if fill.side is OrderSide.BUY:
                    total_cost = fill.notional + fill.fee
                    minimum_cash = (
                        self.risk.limits.minimum_cash_reserve * self.config.starting_capital
                    )
                    if total_cost > cash or cash - total_cost < minimum_cash - 1e-7:
                        rejected.append(
                            RejectedPortfolioOrder(
                                order=order,
                                reasons=("insufficient cash or minimum reserve at simulated fill",),
                            )
                        )
                        del pending[symbol]
                        continue
                    old_quantity = position.quantity if position is not None else 0.0
                    old_cost = (
                        old_quantity * position.average_price if position is not None else 0.0
                    )
                    old_fees = position.entry_fees if position is not None else 0.0
                    new_quantity = old_quantity + fill.quantity
                    positions[symbol] = PortfolioPosition(
                        asset=bar.asset,
                        strategy_version=order.strategy_version,
                        quantity=new_quantity,
                        average_price=(old_cost + fill.notional) / new_quantity,
                        entry_timestamp=(
                            position.entry_timestamp if position is not None else fill.timestamp
                        ),
                        entry_fees=old_fees + fill.fee,
                    )
                    cash -= total_cost
                elif position is None or position.quantity + 1e-12 < fill.quantity:
                    rejected.append(
                        RejectedPortfolioOrder(
                            order=order, reasons=("insufficient long-only simulated position",)
                        )
                    )
                    del pending[symbol]
                    continue
                else:
                    sold_quantity = min(fill.quantity, position.quantity)
                    allocated_entry_fees = position.entry_fees * sold_quantity / position.quantity
                    cash += sold_quantity * fill.fill_price - fill.fee
                    gross = sold_quantity * (fill.fill_price - position.average_price)
                    net = gross - allocated_entry_fees - fill.fee
                    realised_pnl += net
                    trades.append(
                        Trade(
                            asset=symbol,
                            strategy_version=position.strategy_version,
                            entry_timestamp=position.entry_timestamp,
                            exit_timestamp=fill.timestamp,
                            quantity=sold_quantity,
                            entry_price=position.average_price,
                            exit_price=fill.fill_price,
                            gross_pnl=gross,
                            net_pnl=net,
                            fees=allocated_entry_fees + fill.fee,
                        )
                    )
                    remaining = position.quantity - sold_quantity
                    if remaining > 1e-12:
                        positions[symbol] = position.model_copy(
                            update={
                                "quantity": remaining,
                                "entry_fees": position.entry_fees - allocated_entry_fees,
                            }
                        )
                    else:
                        del positions[symbol]
                turnover_notional += fill.notional
                fills.append(fill)
                del pending[symbol]

            for symbol, bar in current_bars.items():
                latest_prices[symbol] = bar.effective_close
                histories[symbol].append(bar)
            position_values = {
                symbol: position.quantity * latest_prices[symbol]
                for symbol, position in positions.items()
            }
            market_value = sum(position_values.values())
            equity = cash + market_value
            if cash < -1e-7:
                raise RuntimeError("negative cash invariant violated")
            peak = max(peak, equity)
            unrealised = sum(
                position.quantity * (latest_prices[symbol] - position.average_price)
                - position.entry_fees
                for symbol, position in positions.items()
            )
            position_weights = {symbol: value / equity for symbol, value in position_values.items()}
            class_weights: dict[AssetClass, float] = defaultdict(float)
            for symbol, weight in position_weights.items():
                class_weights[positions[symbol].asset.asset_class] += weight
            curve.append(
                PortfolioEquityPoint(
                    timestamp=timestamp,
                    cash=cash,
                    market_value=market_value,
                    equity=equity,
                    realised_pnl=realised_pnl,
                    unrealised_pnl=unrealised,
                    drawdown=equity / peak - 1.0,
                    position_values=position_values,
                    position_weights=position_weights,
                    asset_class_weights=dict(class_weights),
                )
            )
            if timeline_index == len(timeline) - 1:
                continue

            eligible = tuple(
                symbol
                for symbol in sorted(strategies)
                if strategies[symbol].desired_exposure(tuple(histories[symbol])) > 0
            )
            return_history = {
                symbol: periodic_returns([bar.effective_close for bar in history[-61:]])
                for symbol, history in histories.items()
            }
            volatilities = {
                symbol: annualised_volatility(values, self.config.annual_periods)
                for symbol, values in return_history.items()
            }
            plan = allocator.allocate(eligible, volatilities=volatilities, scores=scores)
            target_values = {
                symbol: equity * plan.weights.get(symbol, 0.0) for symbol in strategies
            }
            deltas = {
                symbol: target_values[symbol] - position_values.get(symbol, 0.0)
                for symbol in strategies
            }
            material = self.config.rebalance_threshold * equity
            projected_exposure = sum(position_weights.values())
            projected_class = dict(class_weights)
            projected_cash = cash
            projected_turnover = 0.0
            projected_trades = 0
            risk_statistics = calculate_portfolio_risk_statistics(
                return_history, position_weights, annual_periods=self.config.annual_periods
            )
            for symbol in sorted(deltas, key=lambda key: (deltas[key] > 0, key)):
                delta = deltas[symbol]
                if abs(delta) <= material or symbol in pending:
                    continue
                bar = current_bars[symbol]
                strategy = strategies[symbol]
                side = OrderSide.BUY if delta > 0 else OrderSide.SELL
                if side is OrderSide.BUY:
                    estimated_price = bar.effective_close * (
                        1
                        + self.config.costs.spread_bps / 20_000
                        + self.config.costs.slippage_bps / 10_000
                    )
                    quantity = delta / estimated_price
                    requested_notional = delta
                else:
                    position = positions.get(symbol)
                    if position is None:
                        continue
                    quantity = min(position.quantity, abs(delta) / bar.effective_close)
                    requested_notional = quantity * bar.effective_close
                if quantity <= 1e-12:
                    continue
                order = SimulatedOrder(
                    order_id=self._order_id(dataset_id, strategy, symbol, side, timestamp),
                    strategy_version=strategy.spec.version_key,
                    asset=bar.asset,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=quantity,
                    decision_timestamp=timestamp,
                )
                correlated_exposure = sum(
                    weight
                    for other, weight in position_weights.items()
                    if other != symbol
                    and abs(risk_statistics.correlation_matrix.get(symbol, {}).get(other, 0.0))
                    >= self.risk.limits.correlation_threshold
                )
                context = RiskContext(
                    portfolio_equity=equity,
                    current_portfolio_exposure=projected_exposure,
                    current_asset_class_exposure=projected_class,
                    open_position_symbols=frozenset(positions),
                    current_drawdown=abs(curve[-1].drawdown),
                    trades_in_period=projected_trades,
                    market_timestamp=timestamp,
                    evaluation_timestamp=timestamp,
                    previous_price=(
                        histories[symbol][-2].effective_close
                        if len(histories[symbol]) > 1
                        else None
                    ),
                    cash_available=projected_cash,
                    current_turnover=projected_turnover,
                    current_position_weights=position_weights,
                    correlated_exposure=correlated_exposure,
                )
                decision = self.risk.evaluate(
                    symbol=symbol,
                    asset_class=bar.asset.asset_class,
                    side=side,
                    requested_notional=requested_notional,
                    requested_price=bar.effective_close,
                    context=context,
                )
                if not decision.allowed:
                    rejected.append(RejectedPortfolioOrder(order=order, reasons=decision.reasons))
                    continue
                pending[symbol] = order
                fraction = requested_notional / equity
                projected_turnover += fraction
                projected_trades += 1
                if side is OrderSide.BUY:
                    projected_exposure += fraction
                    projected_class[bar.asset.asset_class] = (
                        projected_class.get(bar.asset.asset_class, 0.0) + fraction
                    )
                    projected_cash -= requested_notional
                else:
                    projected_exposure = max(0.0, projected_exposure - fraction)
                    projected_class[bar.asset.asset_class] = max(
                        0.0, projected_class.get(bar.asset.asset_class, 0.0) - fraction
                    )
                    projected_cash += requested_notional

        metrics = _portfolio_metrics(curve, fills, trades, self.config.annual_periods)
        benchmarks = calculate_portfolio_benchmarks(
            bars_by_symbol,
            timeline,
            curve,
            metrics,
            annual_periods=self.config.annual_periods,
        )
        strategy_attr, asset_attr, class_attr = self._attribution(
            trades, fills, positions, latest_prices
        )
        return PortfolioBacktestResult(
            dataset_id=dataset_id,
            universe=universe,
            start=timeline[0],
            end=timeline[-1],
            starting_capital=self.config.starting_capital,
            final_equity=curve[-1].equity,
            adjustment_policy=adjustment_policy,
            costs=self.config.costs,
            metrics=metrics,
            benchmarks=benchmarks,
            fills=tuple(fills),
            rejected_orders=tuple(rejected),
            trades=tuple(trades),
            equity_curve=tuple(curve),
            final_positions=dict(positions),
            strategy_attribution=strategy_attr,
            asset_attribution=asset_attr,
            asset_class_attribution=class_attr,
            allocation_method=allocator.name,
        )

    @staticmethod
    def _attribution(
        trades: Sequence[Trade],
        fills: Sequence[SimulatedFill],
        positions: Mapping[str, PortfolioPosition],
        latest_prices: Mapping[str, float],
    ) -> tuple[
        tuple[PortfolioAttribution, ...],
        tuple[PortfolioAttribution, ...],
        tuple[PortfolioAttribution, ...],
    ]:
        buckets: dict[str, dict[str, list[float]]] = {
            "strategy": defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]),
            "asset": defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]),
            "asset_class": defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]),
        }
        asset_classes = {fill.asset.symbol: fill.asset.asset_class.value for fill in fills}
        for position in positions.values():
            asset_classes[position.asset.symbol] = position.asset.asset_class.value
            unrealised = (
                position.quantity * (latest_prices[position.asset.symbol] - position.average_price)
                - position.entry_fees
            )
            buckets["strategy"][position.strategy_version][1] += unrealised
            buckets["asset"][position.asset.symbol][1] += unrealised
            buckets["asset_class"][position.asset.asset_class.value][1] += unrealised
        for trade in trades:
            buckets["strategy"][trade.strategy_version][0] += trade.net_pnl
            buckets["asset"][trade.asset][0] += trade.net_pnl
            buckets["asset_class"][asset_classes[trade.asset]][0] += trade.net_pnl
        for fill in fills:
            keys = {
                "strategy": fill.strategy_version,
                "asset": fill.asset.symbol,
                "asset_class": fill.asset.asset_class.value,
            }
            for dimension, key in keys.items():
                buckets[dimension][key][2] += fill.fee
                buckets[dimension][key][3] += fill.notional

        def records(dimension: str) -> tuple[PortfolioAttribution, ...]:
            return tuple(
                PortfolioAttribution(
                    dimension=dimension,
                    key=key,
                    realised_net_pnl=values[0],
                    unrealised_pnl=values[1],
                    fees=values[2],
                    turnover_notional=values[3],
                )
                for key, values in sorted(buckets[dimension].items())
            )

        return records("strategy"), records("asset"), records("asset_class")
