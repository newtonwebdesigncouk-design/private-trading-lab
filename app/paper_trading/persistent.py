"""Restart-safe, idempotent scheduled paper cycles backed by SQLAlchemy."""

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, sessionmaker

from app.backtesting.models import CostAssumptions, SimulatedFill, SimulatedOrder
from app.database.tables import (
    PaperAccountRow,
    PaperAuditRow,
    PaperCycleRow,
    PaperFillRow,
    PaperOrderRow,
    PaperPortfolioSnapshotRow,
)
from app.models.enums import AssetClass, OrderSide, OrderStatus, OrderType
from app.models.market import MarketBar
from app.paper_trading.engine import (
    InMemoryAuditSink,
    PaperAccount,
    PaperPosition,
    PaperTradingEngine,
)
from app.risk import RiskContext, RiskEngine
from app.strategies.base import Strategy


class PaperCycleStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


class PersistentPaperAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    account: PaperAccount
    pending_orders: tuple[SimulatedOrder, ...]
    kill_switch: bool
    last_cycle_id: str | None = None


class PaperCycleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    cycle_id: str
    account_id: str
    dataset_id: str
    status: PaperCycleStatus
    processed: bool
    account: PaperAccount
    orders: tuple[SimulatedOrder, ...] = ()
    fills: tuple[SimulatedFill, ...] = ()
    audit_events: tuple[dict[str, Any], ...] = ()


class PaperScheduler(Protocol):
    def next_expected_cycle(self, after: datetime) -> datetime: ...


class FixedIntervalPaperScheduler:
    def __init__(self, interval: timedelta) -> None:
        if interval <= timedelta(0):
            raise ValueError("scheduler interval must be positive")
        self.interval = interval

    def next_expected_cycle(self, after: datetime) -> datetime:
        return after + self.interval


class PersistentPaperRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create_account(
        self, account_id: str, *, starting_cash: float, kill_switch: bool = False
    ) -> PersistentPaperAccount:
        if starting_cash <= 0:
            raise ValueError("starting_cash must be positive")
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            if session.get(PaperAccountRow, account_id) is not None:
                raise ValueError("paper account already exists")
            session.add(
                PaperAccountRow(
                    account_id=account_id,
                    starting_cash=starting_cash,
                    cash=starting_cash,
                    positions={},
                    pending_orders=[],
                    realised_pnl=0.0,
                    fees_paid=0.0,
                    kill_switch=kill_switch,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.load_account(account_id)

    def load_account(self, account_id: str) -> PersistentPaperAccount:
        with self._sessions() as session:
            row = session.get(PaperAccountRow, account_id)
            if row is None:
                raise KeyError(f"paper account not found: {account_id}")
            positions = {
                symbol: PaperPosition.model_validate(payload)
                for symbol, payload in row.positions.items()
            }
            account = PaperAccount(
                starting_cash=row.starting_cash,
                cash=row.cash,
                positions=positions,
                realised_pnl=row.realised_pnl,
                fees_paid=row.fees_paid,
                equity=row.cash
                + sum(
                    position.quantity * position.average_price for position in positions.values()
                ),
            )
            return PersistentPaperAccount(
                account_id=row.account_id,
                account=account,
                pending_orders=tuple(
                    SimulatedOrder.model_validate(payload) for payload in row.pending_orders
                ),
                kill_switch=row.kill_switch,
                last_cycle_id=row.last_cycle_id,
            )

    def begin_cycle(
        self,
        cycle_id: str,
        *,
        account_id: str,
        dataset_id: str,
        market_timestamp: datetime,
    ) -> bool:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            existing = session.get(PaperCycleRow, cycle_id)
            if existing is not None:
                if existing.status != PaperCycleStatus.FAILED.value:
                    return False
                existing.status = PaperCycleStatus.IN_PROGRESS.value
                existing.retry_count += 1
                existing.error = None
                existing.started_at = now
                return True
            session.add(
                PaperCycleRow(
                    cycle_id=cycle_id,
                    account_id=account_id,
                    dataset_id=dataset_id,
                    market_timestamp=market_timestamp,
                    status=PaperCycleStatus.IN_PROGRESS.value,
                    retry_count=0,
                    payload={},
                    started_at=now,
                )
            )
        return True

    def complete_cycle(
        self,
        cycle_id: str,
        state: PersistentPaperAccount,
        *,
        orders: Sequence[SimulatedOrder],
        fills: Sequence[SimulatedFill],
        audit_events: Sequence[dict[str, Any]],
        timestamp: datetime,
        status: PaperCycleStatus = PaperCycleStatus.COMPLETED,
    ) -> None:
        now = datetime.now(UTC)
        filled_ids = {fill.order_id for fill in fills}
        with self._sessions.begin() as session:
            account_row = session.get(PaperAccountRow, state.account_id)
            cycle = session.get(PaperCycleRow, cycle_id)
            if account_row is None or cycle is None:
                raise RuntimeError("paper cycle persistence state is missing")
            account_row.cash = state.account.cash
            account_row.positions = {
                symbol: position.model_dump(mode="json")
                for symbol, position in state.account.positions.items()
            }
            account_row.pending_orders = [
                order.model_dump(mode="json") for order in state.pending_orders
            ]
            account_row.realised_pnl = state.account.realised_pnl
            account_row.fees_paid = state.account.fees_paid
            account_row.last_cycle_id = cycle_id
            account_row.updated_at = now
            for order in orders:
                order_row = session.get(PaperOrderRow, order.order_id)
                order_status = (
                    OrderStatus.FILLED.value
                    if order.order_id in filled_ids
                    else OrderStatus.PENDING.value
                )
                if order_row is None:
                    session.add(
                        PaperOrderRow(
                            order_id=order.order_id,
                            account_id=state.account_id,
                            cycle_id=cycle_id,
                            strategy_version=order.strategy_version,
                            status=order_status,
                            payload=order.model_dump(mode="json"),
                            created_at=order.decision_timestamp,
                        )
                    )
                else:
                    order_row.status = order_status
            for fill in fills:
                fill_id = hashlib.sha256(
                    f"{fill.order_id}|{fill.timestamp.isoformat()}".encode()
                ).hexdigest()
                if session.get(PaperFillRow, fill_id) is None:
                    session.add(
                        PaperFillRow(
                            fill_id=fill_id,
                            order_id=fill.order_id,
                            account_id=state.account_id,
                            cycle_id=cycle_id,
                            strategy_version=fill.strategy_version,
                            payload=fill.model_dump(mode="json"),
                            filled_at=fill.timestamp,
                        )
                    )
            session.add(
                PaperPortfolioSnapshotRow(
                    account_id=state.account_id,
                    cycle_id=cycle_id,
                    timestamp=timestamp,
                    account=state.account.model_dump(mode="json"),
                )
            )
            for event in audit_events:
                session.add(
                    PaperAuditRow(
                        event_type=str(event["event_type"]),
                        payload=dict(event["payload"]),
                        occurred_at=datetime.fromisoformat(str(event["timestamp"])),
                    )
                )
            cycle.status = status.value
            cycle.payload = {
                "orders": len(orders),
                "fills": len(fills),
                "equity": state.account.equity,
            }
            cycle.completed_at = now

    def fail_cycle(self, cycle_id: str, error: str) -> None:
        with self._sessions.begin() as session:
            cycle = session.get(PaperCycleRow, cycle_id)
            if cycle is None:
                raise RuntimeError("paper cycle persistence state is missing")
            cycle.status = PaperCycleStatus.FAILED.value
            cycle.error = error
            cycle.completed_at = datetime.now(UTC)
            session.add(
                PaperAuditRow(
                    event_type="PAPER_CYCLE_FAILED",
                    payload={"cycle_id": cycle_id, "error": error},
                    occurred_at=datetime.now(UTC),
                )
            )


class PersistentPaperLab:
    """Runs exactly one local simulation cycle and commits it atomically."""

    def __init__(
        self,
        repository: PersistentPaperRepository,
        risk_engine: RiskEngine,
        *,
        costs: CostAssumptions | None = None,
    ) -> None:
        self.repository = repository
        self.risk = risk_engine
        self.costs = costs

    @staticmethod
    def cycle_id(
        account_id: str, dataset_id: str, bars_by_symbol: Mapping[str, Sequence[MarketBar]]
    ) -> str:
        points = "|".join(
            f"{symbol}:{bars[-1].timestamp.isoformat()}"
            for symbol, bars in sorted(bars_by_symbol.items())
        )
        return hashlib.sha256(f"{account_id}|{dataset_id}|{points}".encode()).hexdigest()

    def run_cycle(
        self,
        account_id: str,
        dataset_id: str,
        strategies: Mapping[str, Strategy],
        bars_by_symbol: Mapping[str, Sequence[MarketBar]],
        *,
        evaluation_timestamp: datetime,
    ) -> PaperCycleResult:
        if not bars_by_symbol or set(strategies) != set(bars_by_symbol):
            raise ValueError("strategies and non-empty bar histories must have identical symbols")
        if any(not bars for bars in bars_by_symbol.values()):
            raise ValueError("paper cycles require a bar history for every instrument")
        state = self.repository.load_account(account_id)
        cycle_id = self.cycle_id(account_id, dataset_id, bars_by_symbol)
        timestamp = max(bars[-1].timestamp for bars in bars_by_symbol.values())
        if not self.repository.begin_cycle(
            cycle_id,
            account_id=account_id,
            dataset_id=dataset_id,
            market_timestamp=timestamp,
        ):
            return PaperCycleResult(
                cycle_id=cycle_id,
                account_id=account_id,
                dataset_id=dataset_id,
                status=PaperCycleStatus.DUPLICATE,
                processed=False,
                account=state.account,
            )
        audit = InMemoryAuditSink()
        try:
            if state.kill_switch or self.risk.kill_switch_engaged:
                audit.record(
                    "PAPER_CYCLE_BLOCKED",
                    {"cycle_id": cycle_id, "reason": "simulation kill switch is engaged"},
                    evaluation_timestamp,
                )
                self.repository.complete_cycle(
                    cycle_id,
                    state,
                    orders=(),
                    fills=(),
                    audit_events=audit.events,
                    timestamp=timestamp,
                    status=PaperCycleStatus.BLOCKED,
                )
                return PaperCycleResult(
                    cycle_id=cycle_id,
                    account_id=account_id,
                    dataset_id=dataset_id,
                    status=PaperCycleStatus.BLOCKED,
                    processed=True,
                    account=state.account,
                    audit_events=tuple(audit.events),
                )
            engine = PaperTradingEngine(
                starting_cash=state.account.starting_cash,
                risk_engine=self.risk,
                audit_sink=audit,
                costs=self.costs,
                account_state=state.account,
                pending_orders=state.pending_orders,
            )
            new_fills: list[SimulatedFill] = []
            latest_bars = {symbol: bars[-1] for symbol, bars in bars_by_symbol.items()}
            for symbol in sorted(latest_bars):
                new_fills.extend(engine.process_bar(latest_bars[symbol]))
            account = engine.account
            class_exposure: dict[AssetClass, float] = defaultdict(float)
            position_weights: dict[str, float] = {}
            for symbol, position in account.positions.items():
                value = position.quantity * latest_bars[symbol].effective_close
                weight = value / account.equity
                position_weights[symbol] = weight
                class_exposure[position.asset.asset_class] += weight
            for symbol in sorted(strategies):
                if any(order.asset.symbol == symbol for order in engine.pending_orders):
                    continue
                strategy = strategies[symbol]
                bars = bars_by_symbol[symbol]
                bar = bars[-1]
                target = strategy.desired_exposure(tuple(bars))
                current_position = account.positions.get(symbol)
                if current_position is None and target > 0:
                    budget = account.equity * min(
                        target, self.risk.limits.maximum_position_percentage
                    )
                    quantity = budget / bar.effective_close
                    side = OrderSide.BUY
                elif current_position is not None and target == 0:
                    quantity = current_position.quantity
                    side = OrderSide.SELL
                else:
                    continue
                context = RiskContext(
                    portfolio_equity=account.equity,
                    current_portfolio_exposure=account.market_value / account.equity,
                    current_asset_class_exposure=class_exposure,
                    open_position_symbols=frozenset(account.positions),
                    market_timestamp=bar.timestamp,
                    evaluation_timestamp=evaluation_timestamp,
                    previous_price=bars[-2].effective_close if len(bars) > 1 else None,
                    cash_available=account.cash,
                    current_position_weights=position_weights,
                    trades_in_period=len(engine.fills),
                )
                order_id = hashlib.sha256(
                    f"{cycle_id}|{strategy.spec.version_key}|{symbol}|{side}".encode()
                ).hexdigest()[:24]
                try:
                    engine.create_simulated_order(
                        order_id=order_id,
                        strategy_version=strategy.spec.version_key,
                        asset=bar.asset,
                        side=side,
                        order_type=OrderType.MARKET,
                        quantity=quantity,
                        decision_timestamp=bar.timestamp,
                        estimated_price=bar.effective_close,
                        risk_context=context,
                    )
                except PermissionError:
                    continue
            updated = PersistentPaperAccount(
                account_id=account_id,
                account=engine.account,
                pending_orders=engine.pending_orders,
                kill_switch=state.kill_switch,
                last_cycle_id=cycle_id,
            )
            self.repository.complete_cycle(
                cycle_id,
                updated,
                orders=engine.orders,
                fills=new_fills,
                audit_events=audit.events,
                timestamp=timestamp,
            )
            return PaperCycleResult(
                cycle_id=cycle_id,
                account_id=account_id,
                dataset_id=dataset_id,
                status=PaperCycleStatus.COMPLETED,
                processed=True,
                account=engine.account,
                orders=engine.orders,
                fills=tuple(new_fills),
                audit_events=tuple(audit.events),
            )
        except Exception as exc:
            self.repository.fail_cycle(cycle_id, str(exc))
            raise
