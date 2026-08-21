"""Multiple frozen strategy sleeves sharing one cash-only simulated risk budget."""

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime

from app.backtesting.analytics import periodic_returns
from app.backtesting.engine import ExecutionModel
from app.backtesting.models import SimulatedOrder, Trade
from app.forward.models import (
    ForwardFill,
    ForwardPendingOrder,
    ForwardPortfolioSnapshot,
    ForwardPortfolioState,
    ForwardPortfolioStepResult,
    ForwardPosition,
    ForwardSignal,
    ForwardTrial,
    ForwardTrialLedger,
    ForwardTrialManifest,
    ForwardTrialSnapshot,
    canonical_hash,
)
from app.models.enums import AssetClass, ForwardTrialState, OrderSide, OrderType
from app.models.market import MarketBar
from app.risk import RiskContext, RiskEngine, calculate_portfolio_risk_statistics
from app.strategies.base import Strategy


def _order_id(
    cycle_id: str, trial_id: str, symbol: str, side: OrderSide, timestamp: datetime
) -> str:
    value = f"{cycle_id}|{trial_id}|{symbol}|{side.value}|{timestamp.isoformat()}"
    return hashlib.sha256(value.encode()).hexdigest()[:24]


class ForwardPortfolioEngine:
    """Local PAPER accounting; strategies never receive cash or risk-policy mutation access."""

    def __init__(self, risk_engine: RiskEngine) -> None:
        self.risk = risk_engine

    def initial_state(self, manifests: Sequence[ForwardTrialManifest]) -> ForwardPortfolioState:
        if not manifests:
            raise ValueError("a forward portfolio requires at least one frozen trial")
        first = manifests[0]
        if any(item.portfolio_id != first.portfolio_id for item in manifests):
            raise ValueError("forward trials must share one frozen portfolio ID")
        if any(
            item.portfolio_starting_capital != first.portfolio_starting_capital
            for item in manifests
        ):
            raise ValueError("forward trials must share frozen portfolio capital")
        if any(item.risk_policy != first.risk_policy for item in manifests):
            raise ValueError("concurrent trials must share one immutable risk policy")
        if first.risk_policy.limits != self.risk.limits:
            raise ValueError("Risk Engine limits differ from the frozen forward policy")
        if len({item.trial_id for item in manifests}) != len(manifests):
            raise ValueError("duplicate forward trial in portfolio")
        total_weight = sum(item.allocation_weight for item in manifests)
        if total_weight > 1 + 1e-12:
            raise ValueError("frozen strategy allocations exceed portfolio capital")
        ledgers = {
            item.trial_id: ForwardTrialLedger(
                trial_id=item.trial_id,
                starting_cash=item.allocated_capital,
                cash=item.allocated_capital,
            )
            for item in manifests
        }
        reserve = first.portfolio_starting_capital * (1.0 - total_weight)
        return ForwardPortfolioState(
            portfolio_id=first.portfolio_id,
            starting_capital=first.portfolio_starting_capital,
            reserve_cash=max(reserve, 0.0),
            ledgers=ledgers,
            peak_equity=first.portfolio_starting_capital,
        )

    @staticmethod
    def _ledger_values(
        state: ForwardPortfolioState,
    ) -> tuple[dict[str, float], dict[str, float], float, float]:
        market_values: dict[str, float] = {}
        equities: dict[str, float] = {}
        for trial_id, ledger in state.ledgers.items():
            market = sum(
                position.quantity * state.latest_prices.get(symbol, position.average_price)
                for symbol, position in ledger.positions.items()
            )
            market_values[trial_id] = market
            equities[trial_id] = ledger.cash + market
        total_cash = state.reserve_cash + sum(item.cash for item in state.ledgers.values())
        total_market = sum(market_values.values())
        return market_values, equities, total_cash, total_market

    def step(
        self,
        state: ForwardPortfolioState,
        trials: Mapping[str, ForwardTrial],
        strategies: Mapping[str, Strategy],
        current_bars: Mapping[str, MarketBar],
        histories: Mapping[str, Sequence[MarketBar]],
        *,
        cycle_id: str,
        timestamp: datetime,
        evaluation_timestamp: datetime,
        provenance: object,
        allow_new_orders: bool,
        prior_snapshots: Sequence[ForwardPortfolioSnapshot] = (),
    ) -> ForwardPortfolioStepResult:
        from app.models.enums import ObservationProvenance

        if not isinstance(provenance, ObservationProvenance):
            raise TypeError("forward portfolio provenance must be explicit")
        if set(trials) != set(strategies) or set(trials) != set(state.ledgers):
            raise ValueError("trials, strategies, and frozen ledgers must match")
        if any(trial.manifest.portfolio_id != state.portfolio_id for trial in trials.values()):
            raise ValueError("trial portfolio identity mismatch")

        period_date = timestamp.date().isoformat()
        period_turnover = state.period_turnover if state.risk_period_date == period_date else 0.0
        period_trades = state.period_trades if state.risk_period_date == period_date else 0
        ledgers = dict(state.ledgers)
        pending: list[ForwardPendingOrder] = []
        fills: list[ForwardFill] = []
        trades: dict[str, list[Trade]] = defaultdict(list)
        rejections: dict[str, list[str]] = defaultdict(list)
        latest_prices = dict(state.latest_prices)

        for pending_order in sorted(
            state.pending_orders, key=lambda item: (item.trial_id, item.order.asset.symbol)
        ):
            trial = trials[pending_order.trial_id]
            order = pending_order.order
            bar = current_bars.get(order.asset.symbol)
            if bar is None:
                pending.append(pending_order)
                continue
            if order.side is OrderSide.BUY and trial.state in {
                ForwardTrialState.PAUSED_DATA_QUALITY,
                ForwardTrialState.PAUSED_RISK,
                ForwardTrialState.FAILED_FORWARD,
                ForwardTrialState.RETIRED,
            }:
                rejections[trial.manifest.trial_id].append(
                    "trial lifecycle state blocks pending simulated buy"
                )
                continue
            fill = ExecutionModel(trial.manifest.costs).try_fill(order, bar)
            if fill is None:
                pending.append(pending_order)
                continue
            ledger = ledgers[pending_order.trial_id]
            position = ledger.positions.get(order.asset.symbol)
            positions = dict(ledger.positions)
            if fill.side is OrderSide.BUY:
                total_cost = fill.notional + fill.fee
                if total_cost > ledger.cash + 1e-9:
                    rejections[pending_order.trial_id].append(
                        "frozen trial sleeve has insufficient simulated cash"
                    )
                    continue
                old_quantity = position.quantity if position else 0.0
                old_cost = old_quantity * position.average_price if position else 0.0
                old_fees = position.entry_fees if position else 0.0
                quantity = old_quantity + fill.quantity
                positions[order.asset.symbol] = ForwardPosition(
                    asset=order.asset,
                    quantity=quantity,
                    average_price=(old_cost + fill.notional) / quantity,
                    entry_timestamp=(position.entry_timestamp if position else fill.timestamp),
                    entry_fees=old_fees + fill.fee,
                )
                ledger = ledger.model_copy(
                    update={
                        "cash": ledger.cash - total_cost,
                        "positions": positions,
                        "fees_paid": ledger.fees_paid + fill.fee,
                        "turnover_notional": ledger.turnover_notional + fill.notional,
                    }
                )
            elif position is None or position.quantity + 1e-12 < fill.quantity:
                rejections[pending_order.trial_id].append(
                    "simulated sell exceeds the long-only trial position"
                )
                continue
            else:
                quantity = min(fill.quantity, position.quantity)
                entry_fees = position.entry_fees * quantity / position.quantity
                proceeds = quantity * fill.fill_price - fill.fee
                gross_pnl = quantity * (fill.fill_price - position.average_price)
                net_pnl = gross_pnl - entry_fees - fill.fee
                trade = Trade(
                    asset=order.asset.symbol,
                    strategy_version=order.strategy_version,
                    entry_timestamp=position.entry_timestamp,
                    exit_timestamp=fill.timestamp,
                    quantity=quantity,
                    entry_price=position.average_price,
                    exit_price=fill.fill_price,
                    gross_pnl=gross_pnl,
                    net_pnl=net_pnl,
                    fees=entry_fees + fill.fee,
                )
                remaining = position.quantity - quantity
                if remaining > 1e-12:
                    positions[order.asset.symbol] = position.model_copy(
                        update={
                            "quantity": remaining,
                            "entry_fees": position.entry_fees - entry_fees,
                        }
                    )
                else:
                    positions.pop(order.asset.symbol, None)
                ledger = ledger.model_copy(
                    update={
                        "cash": ledger.cash + proceeds,
                        "positions": positions,
                        "realised_pnl": ledger.realised_pnl + net_pnl,
                        "fees_paid": ledger.fees_paid + fill.fee,
                        "turnover_notional": ledger.turnover_notional + fill.notional,
                        "trades": (*ledger.trades, trade),
                    }
                )
                trades[pending_order.trial_id].append(trade)
            ledgers[pending_order.trial_id] = ledger
            fills.append(ForwardFill(trial_id=pending_order.trial_id, fill=fill))
            period_turnover += fill.notional / state.starting_capital
            period_trades += 1

        for symbol, bar in current_bars.items():
            latest_prices[symbol] = bar.effective_close
            if bar.dividend:
                for trial_id, ledger in tuple(ledgers.items()):
                    position = ledger.positions.get(symbol)
                    if position is not None:
                        ledgers[trial_id] = ledger.model_copy(
                            update={"cash": ledger.cash + position.quantity * bar.dividend}
                        )

        interim = state.model_copy(
            update={
                "ledgers": ledgers,
                "pending_orders": tuple(pending),
                "latest_prices": latest_prices,
                "risk_period_date": period_date,
                "period_turnover": period_turnover,
                "period_trades": period_trades,
            }
        )
        market_values, equities, total_cash, total_market = self._ledger_values(interim)
        total_equity = total_cash + total_market
        if total_cash < -1e-9 or any(item.cash < -1e-9 for item in ledgers.values()):
            raise RuntimeError("negative cash invariant violated in forward PAPER portfolio")
        peak = max(state.peak_equity, total_equity)
        aggregate_positions: dict[str, float] = defaultdict(float)
        class_exposure: dict[AssetClass, float] = defaultdict(float)
        open_symbols: set[str] = set()
        trial_position_weights: dict[str, dict[str, float]] = {}
        positions_payload: dict[str, dict[str, object]] = {}
        for trial_id, ledger in ledgers.items():
            trial_position_weights[trial_id] = {}
            for symbol, position in ledger.positions.items():
                value = position.quantity * latest_prices[symbol]
                aggregate_positions[symbol] += value / total_equity
                class_exposure[position.asset.asset_class] += value / total_equity
                open_symbols.add(symbol)
                trial_position_weights[trial_id][symbol] = value / total_equity
                positions_payload[f"{trial_id}|{symbol}"] = {
                    "trial_id": trial_id,
                    "asset": position.asset.model_dump(mode="json"),
                    "quantity": position.quantity,
                    "average_price": position.average_price,
                    "market_value": value,
                    "portfolio_weight": value / total_equity,
                }

        signals: list[ForwardSignal] = []
        new_orders: list[ForwardPendingOrder] = []
        return_history = {
            symbol: periodic_returns([bar.effective_close for bar in values[-61:]])
            for symbol, values in histories.items()
        }
        risk_stats = calculate_portfolio_risk_statistics(
            return_history, aggregate_positions, annual_periods=252
        )
        daily_return = total_equity / prior_snapshots[-1].equity - 1.0 if prior_snapshots else 0.0
        weekly_return = (
            total_equity / prior_snapshots[-5].equity - 1.0
            if len(prior_snapshots) >= 5
            else daily_return
        )
        for trial_id in sorted(trials):
            trial = trials[trial_id]
            manifest = trial.manifest
            strategy = strategies[trial_id]
            ledger = ledgers[trial_id]
            asset = manifest.assets[0]
            bar = current_bars.get(asset.symbol)
            if bar is None:
                continue
            history = histories.get(asset.symbol, ())
            desired = strategy.desired_exposure(history)
            if not 0 <= desired <= 1:
                raise ValueError("forward strategy requested exposure outside [0, 1]")
            if trial.state in {
                ForwardTrialState.PAUSED_DATA_QUALITY,
                ForwardTrialState.PAUSED_RISK,
                ForwardTrialState.FAILED_FORWARD,
                ForwardTrialState.RETIRED,
            }:
                desired = 0.0
            regime = None
            signals.append(
                ForwardSignal(
                    signal_id=(
                        "forward-signal-"
                        + canonical_hash(
                            {"cycle": cycle_id, "trial": trial_id, "desired": desired}
                        )[:24]
                    ),
                    trial_id=trial_id,
                    cycle_id=cycle_id,
                    timestamp=timestamp,
                    desired_exposure=desired,
                    regime=regime,
                )
            )
            ledgers[trial_id] = ledger.model_copy(update={"signal_count": ledger.signal_count + 1})
            if not allow_new_orders or any(item.trial_id == trial_id for item in pending):
                continue
            position = ledger.positions.get(asset.symbol)
            if position is None and desired > 0:
                trial_cap = total_equity * manifest.risk_policy.maximum_strategy_allocation
                sleeve_buffer = max(self.risk.limits.minimum_cash_reserve, 0.02)
                target = min(
                    equities[trial_id] * desired,
                    trial_cap,
                    ledger.cash * (1.0 - sleeve_buffer),
                )
                estimated_fee = ExecutionModel(manifest.costs).commission(target)
                estimated_price = bar.effective_close * (
                    1 + manifest.costs.spread_bps / 20_000 + manifest.costs.slippage_bps / 10_000
                )
                quantity = max(0.0, min(target, ledger.cash - estimated_fee) / estimated_price)
                side = OrderSide.BUY
            elif position is not None and desired == 0:
                quantity = position.quantity
                target = quantity * bar.effective_close
                side = OrderSide.SELL
            else:
                continue
            if quantity <= 1e-12:
                continue
            order = SimulatedOrder(
                order_id=_order_id(cycle_id, trial_id, asset.symbol, side, timestamp),
                strategy_version=manifest.strategy.version_key,
                asset=asset,
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                decision_timestamp=timestamp,
            )
            correlated = sum(
                weight
                for other, weight in aggregate_positions.items()
                if other != asset.symbol
                and abs(risk_stats.correlation_matrix.get(asset.symbol, {}).get(other, 0.0))
                >= self.risk.limits.correlation_threshold
            )
            decision = self.risk.evaluate(
                symbol=asset.symbol,
                asset_class=asset.asset_class,
                side=side,
                requested_notional=target,
                requested_price=bar.effective_close,
                context=RiskContext(
                    portfolio_equity=total_equity,
                    current_portfolio_exposure=total_market / total_equity,
                    current_asset_class_exposure=class_exposure,
                    open_position_symbols=frozenset(open_symbols),
                    daily_return=daily_return,
                    weekly_return=weekly_return,
                    current_drawdown=1.0 - total_equity / peak,
                    trades_in_period=period_trades,
                    market_timestamp=bar.timestamp,
                    evaluation_timestamp=evaluation_timestamp,
                    previous_price=(history[-2].effective_close if len(history) > 1 else None),
                    cash_available=total_cash,
                    current_turnover=period_turnover,
                    current_position_weights=aggregate_positions,
                    correlated_exposure=correlated,
                ),
            )
            current_trial_allocation = market_values[trial_id] / total_equity
            requested_fraction = target / total_equity
            reasons = list(decision.reasons)
            if (
                side is OrderSide.BUY
                and current_trial_allocation + requested_fraction
                > manifest.risk_policy.maximum_strategy_allocation + 1e-12
            ):
                reasons.append("maximum frozen strategy allocation exceeded")
            if reasons:
                rejections[trial_id].extend(reasons)
                continue
            wrapped = ForwardPendingOrder(trial_id=trial_id, order=order)
            pending.append(wrapped)
            new_orders.append(wrapped)

        updated = interim.model_copy(
            update={
                "ledgers": ledgers,
                "pending_orders": tuple(pending),
                "peak_equity": peak,
                "period_turnover": period_turnover,
                "period_trades": period_trades,
                "last_cycle_id": cycle_id,
            }
        )
        market_values, equities, total_cash, total_market = self._ledger_values(updated)
        total_equity = total_cash + total_market
        trial_snapshots: list[ForwardTrialSnapshot] = []
        for trial_id, ledger in updated.ledgers.items():
            unrealised = sum(
                position.quantity * (latest_prices[symbol] - position.average_price)
                - position.entry_fees
                for symbol, position in ledger.positions.items()
            )
            trial_equity = equities[trial_id]
            trial_snapshots.append(
                ForwardTrialSnapshot(
                    trial_id=trial_id,
                    timestamp=timestamp,
                    cash=ledger.cash,
                    market_value=market_values[trial_id],
                    equity=trial_equity,
                    realised_pnl=ledger.realised_pnl,
                    unrealised_pnl=unrealised,
                    drawdown=max(0.0, 1.0 - trial_equity / ledger.starting_cash),
                    allocation=trial_equity / total_equity,
                )
            )
        snapshot = ForwardPortfolioSnapshot(
            portfolio_id=state.portfolio_id,
            cycle_id=cycle_id,
            provenance=provenance,
            timestamp=timestamp,
            cash=total_cash,
            market_value=total_market,
            equity=total_equity,
            drawdown=max(0.0, 1.0 - total_equity / peak),
            gross_exposure=total_market / total_equity,
            positions=positions_payload,
            trial_snapshots=tuple(sorted(trial_snapshots, key=lambda item: item.trial_id)),
            asset_class_exposure={key.value: value for key, value in class_exposure.items()},
        )
        return ForwardPortfolioStepResult(
            state=updated,
            snapshot=snapshot,
            signals=tuple(signals),
            orders=tuple(new_orders),
            fills=tuple(fills),
            trades={key: tuple(value) for key, value in trades.items()},
            risk_rejections={key: tuple(value) for key, value in rejections.items()},
        )
