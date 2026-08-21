"""Independent risk controls and paper-accounting tests."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import bars_from_closes

from app.models.enums import AssetClass, OrderSide, OrderType
from app.models.market import Asset
from app.paper_trading import InMemoryAuditSink, PaperTradingEngine
from app.risk import RiskContext, RiskEngine, RiskLimits


def context(
    timestamp: datetime,
    *,
    exposure: float = 0.0,
    daily_return: float = 0.0,
    previous_price: float | None = 100.0,
) -> RiskContext:
    return RiskContext(
        portfolio_equity=10_000,
        current_portfolio_exposure=exposure,
        current_asset_class_exposure={AssetClass.EQUITY: exposure},
        market_timestamp=timestamp,
        evaluation_timestamp=timestamp,
        daily_return=daily_return,
        previous_price=previous_price,
    )


def test_kill_switch_rejects_simulated_order() -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    decision = RiskEngine(kill_switch=True).evaluate(
        symbol="TEST",
        asset_class=AssetClass.EQUITY,
        side=OrderSide.BUY,
        requested_notional=1_000,
        requested_price=100,
        context=context(timestamp),
    )
    assert not decision.allowed
    assert "TRADING_KILL_SWITCH" in decision.reasons[0]


def test_position_and_portfolio_limits_are_independent_of_strategy() -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    engine = RiskEngine(
        RiskLimits(
            maximum_position_percentage=0.1,
            maximum_asset_class_exposure=0.5,
            maximum_portfolio_exposure=0.5,
        )
    )
    decision = engine.evaluate(
        symbol="TEST",
        asset_class=AssetClass.EQUITY,
        side=OrderSide.BUY,
        requested_notional=2_000,
        requested_price=100,
        context=context(timestamp, exposure=0.4),
    )
    assert not decision.allowed
    assert "maximum position percentage exceeded" in decision.reasons
    assert "maximum portfolio exposure exceeded" in decision.reasons


def test_stale_abnormal_and_loss_controls_reject() -> None:
    market_time = datetime(2024, 1, 1, tzinfo=UTC)
    risk_context = context(market_time, daily_return=-0.05)
    risk_context = risk_context.model_copy(
        update={"evaluation_timestamp": market_time + timedelta(minutes=10)}
    )
    decision = RiskEngine().evaluate(
        symbol="TEST",
        asset_class=AssetClass.EQUITY,
        side=OrderSide.BUY,
        requested_notional=1_000,
        requested_price=130,
        context=risk_context,
    )
    assert not decision.allowed
    assert "market data is stale" in decision.reasons
    assert "abnormal price movement" in decision.reasons
    assert "maximum daily simulated loss reached" in decision.reasons


def test_loss_limit_still_allows_a_risk_reducing_sale() -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    decision = RiskEngine().evaluate(
        symbol="TEST",
        asset_class=AssetClass.EQUITY,
        side=OrderSide.SELL,
        requested_notional=1_000,
        requested_price=100,
        context=context(timestamp, exposure=0.1, daily_return=-0.05),
    )
    assert decision.allowed


def test_paper_engine_records_orders_fills_positions_and_audit(equity: Asset) -> None:
    bars = bars_from_closes(equity, [100, 102, 110])
    audit = InMemoryAuditSink()
    paper = PaperTradingEngine(
        starting_cash=10_000,
        risk_engine=RiskEngine(),
        audit_sink=audit,
    )
    paper.create_simulated_order(
        order_id="buy-1",
        strategy_version="test:v1",
        asset=equity,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        decision_timestamp=bars[0].timestamp,
        estimated_price=100,
        risk_context=context(bars[0].timestamp),
    )
    buy_fills = paper.process_bar(bars[1])
    assert len(buy_fills) == 1
    assert paper.account.positions[equity.symbol].quantity == 10

    paper.create_simulated_order(
        order_id="sell-1",
        strategy_version="test:v1",
        asset=equity,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=10,
        decision_timestamp=bars[1].timestamp,
        estimated_price=102,
        risk_context=context(bars[1].timestamp, exposure=0.1, previous_price=100),
    )
    sell_fills = paper.process_bar(bars[2])
    assert len(sell_fills) == 1
    assert equity.symbol not in paper.account.positions
    assert paper.account.realised_pnl > 0
    event_types = [event["event_type"] for event in audit.events]
    assert event_types.count("SIMULATED_ORDER_CREATED") == 2
    assert event_types.count("SIMULATED_FILL") == 2
    assert event_types.count("PORTFOLIO_SNAPSHOT") == 2


def test_paper_engine_audits_risk_rejection(equity: Asset) -> None:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    audit = InMemoryAuditSink()
    paper = PaperTradingEngine(
        starting_cash=10_000,
        risk_engine=RiskEngine(kill_switch=True),
        audit_sink=audit,
    )
    with pytest.raises(PermissionError):
        paper.create_simulated_order(
            order_id="blocked",
            strategy_version="test:v1",
            asset=equity,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            decision_timestamp=timestamp,
            estimated_price=100,
            risk_context=context(timestamp),
        )
    assert audit.events[0]["event_type"] == "ORDER_REJECTED"
