"""Local-only paper broker with a complete audit trail."""

from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting.engine import ExecutionModel
from app.backtesting.models import CostAssumptions, SimulatedFill, SimulatedOrder
from app.models.enums import OrderSide, OrderType, TradingMode
from app.models.market import Asset, MarketBar
from app.risk import RiskContext, RiskEngine


class AuditSink(Protocol):
    def record(self, event_type: str, payload: dict[str, Any], timestamp: datetime) -> None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, event_type: str, payload: dict[str, Any], timestamp: datetime) -> None:
        self.events.append(
            {"event_type": event_type, "payload": payload, "timestamp": timestamp.isoformat()}
        )


class PaperPosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Asset
    quantity: float
    average_price: float
    entry_fees: float = 0.0


class PaperAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    starting_cash: float
    cash: float
    positions: dict[str, PaperPosition] = Field(default_factory=dict)
    market_value: float = 0.0
    equity: float = 0.0
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    total_pnl: float = 0.0
    fees_paid: float = 0.0


class PaperPortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    account: PaperAccount


class PaperTradingEngine:
    """Accepts simulated orders and processes them against supplied market bars."""

    mode = TradingMode.PAPER

    def __init__(
        self,
        *,
        starting_cash: float,
        risk_engine: RiskEngine,
        audit_sink: AuditSink,
        costs: CostAssumptions | None = None,
    ) -> None:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        self._cash = starting_cash
        self._starting_cash = starting_cash
        self._realised_pnl = 0.0
        self._fees_paid = 0.0
        self._positions: dict[str, PaperPosition] = {}
        self._orders: dict[str, SimulatedOrder] = {}
        self._order_history: list[SimulatedOrder] = []
        self._fills: list[SimulatedFill] = []
        self._latest_prices: dict[str, float] = {}
        self._portfolio_history: list[PaperPortfolioSnapshot] = []
        self._risk = risk_engine
        self._audit = audit_sink
        self._execution = ExecutionModel(costs or CostAssumptions())

    @property
    def account(self) -> PaperAccount:
        market_value = sum(
            position.quantity
            * self._latest_prices.get(position.asset.symbol, position.average_price)
            for position in self._positions.values()
        )
        unrealised_pnl = sum(
            position.quantity
            * (
                self._latest_prices.get(position.asset.symbol, position.average_price)
                - position.average_price
            )
            - position.entry_fees
            for position in self._positions.values()
        )
        equity = self._cash + market_value
        return PaperAccount(
            starting_cash=self._starting_cash,
            cash=self._cash,
            positions=dict(self._positions),
            market_value=market_value,
            equity=equity,
            realised_pnl=self._realised_pnl,
            unrealised_pnl=unrealised_pnl,
            total_pnl=equity - self._starting_cash,
            fees_paid=self._fees_paid,
        )

    @property
    def orders(self) -> tuple[SimulatedOrder, ...]:
        return tuple(self._order_history)

    @property
    def pending_orders(self) -> tuple[SimulatedOrder, ...]:
        return tuple(self._orders.values())

    @property
    def fills(self) -> tuple[SimulatedFill, ...]:
        return tuple(self._fills)

    @property
    def portfolio_history(self) -> tuple[PaperPortfolioSnapshot, ...]:
        return tuple(self._portfolio_history)

    def create_simulated_order(
        self,
        *,
        order_id: str,
        strategy_version: str,
        asset: Asset,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        decision_timestamp: datetime,
        estimated_price: float,
        risk_context: RiskContext,
        limit_price: float | None = None,
    ) -> SimulatedOrder:
        decision = self._risk.evaluate(
            symbol=asset.symbol,
            asset_class=asset.asset_class,
            side=side,
            requested_notional=quantity * estimated_price,
            requested_price=estimated_price,
            context=risk_context,
        )
        if not decision.allowed:
            self._audit.record(
                "ORDER_REJECTED",
                {"order_id": order_id, "reasons": list(decision.reasons)},
                datetime.now(UTC),
            )
            raise PermissionError("; ".join(decision.reasons))
        order = SimulatedOrder(
            order_id=order_id,
            strategy_version=strategy_version,
            asset=asset,
            side=side,
            order_type=order_type,
            quantity=quantity,
            decision_timestamp=decision_timestamp,
            limit_price=limit_price,
        )
        self._orders[order_id] = order
        self._order_history.append(order)
        self._audit.record(
            "SIMULATED_ORDER_CREATED", order.model_dump(mode="json"), datetime.now(UTC)
        )
        return order

    def process_bar(self, bar: MarketBar) -> tuple[SimulatedFill, ...]:
        self._latest_prices[bar.asset.symbol] = bar.effective_close
        new_fills: list[SimulatedFill] = []
        for order_id, order in tuple(self._orders.items()):
            if order.asset != bar.asset:
                continue
            fill = self._execution.try_fill(order, bar)
            if fill is None:
                continue
            position = self._positions.get(bar.asset.symbol)
            if fill.side is OrderSide.BUY:
                total = fill.notional + fill.fee
                if total > self._cash:
                    self._audit.record(
                        "ORDER_REJECTED",
                        {"order_id": order_id, "reasons": ["insufficient simulated cash"]},
                        bar.timestamp,
                    )
                    del self._orders[order_id]
                    continue
                old_quantity = position.quantity if position else 0.0
                old_cost = old_quantity * position.average_price if position else 0.0
                old_fees = position.entry_fees if position else 0.0
                new_quantity = old_quantity + fill.quantity
                self._positions[bar.asset.symbol] = PaperPosition(
                    asset=bar.asset,
                    quantity=new_quantity,
                    average_price=(old_cost + fill.notional) / new_quantity,
                    entry_fees=old_fees + fill.fee,
                )
                self._cash -= total
            else:
                if position is None or position.quantity < fill.quantity:
                    self._audit.record(
                        "ORDER_REJECTED",
                        {"order_id": order_id, "reasons": ["insufficient simulated position"]},
                        bar.timestamp,
                    )
                    del self._orders[order_id]
                    continue
                self._cash += fill.notional - fill.fee
                allocated_entry_fees = position.entry_fees * fill.quantity / position.quantity
                self._realised_pnl += (
                    fill.quantity * (fill.fill_price - position.average_price)
                    - allocated_entry_fees
                    - fill.fee
                )
                remaining = position.quantity - fill.quantity
                if remaining > 1e-12:
                    self._positions[bar.asset.symbol] = position.model_copy(
                        update={
                            "quantity": remaining,
                            "entry_fees": position.entry_fees - allocated_entry_fees,
                        }
                    )
                else:
                    del self._positions[bar.asset.symbol]
            self._fees_paid += fill.fee
            self._fills.append(fill)
            new_fills.append(fill)
            self._audit.record("SIMULATED_FILL", fill.model_dump(mode="json"), bar.timestamp)
            del self._orders[order_id]
        snapshot = PaperPortfolioSnapshot(timestamp=bar.timestamp, account=self.account)
        self._portfolio_history.append(snapshot)
        self._audit.record("PORTFOLIO_SNAPSHOT", snapshot.model_dump(mode="json"), bar.timestamp)
        return tuple(new_fills)
