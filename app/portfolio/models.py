"""Immutable multi-asset portfolio accounting and result models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.backtesting.models import CostAssumptions, SimulatedFill, SimulatedOrder, Trade
from app.models.enums import AdjustmentPolicy, AssetClass
from app.models.market import Asset
from app.universe import UniverseDefinition


class AllocationPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str
    weights: dict[str, float]
    cash_weight: float = Field(ge=0, le=1)


class PortfolioPosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Asset
    strategy_version: str
    quantity: float = Field(gt=0)
    average_price: float = Field(gt=0)
    entry_timestamp: datetime
    entry_fees: float = Field(default=0.0, ge=0)


class PortfolioEquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    cash: float = Field(ge=-1e-7)
    market_value: float = Field(ge=0)
    equity: float = Field(gt=0)
    realised_pnl: float
    unrealised_pnl: float
    drawdown: float = Field(le=0)
    position_values: dict[str, float]
    position_weights: dict[str, float]
    asset_class_weights: dict[AssetClass, float]


class PortfolioMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_return: float
    annualised_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    downside_risk: float
    maximum_drawdown: float
    recovery_time_bars: int | None
    turnover: float
    average_invested_exposure: float
    average_cash_exposure: float
    fees_paid: float
    slippage_cost: float
    number_of_trades: int


class PortfolioAttribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    key: str
    realised_net_pnl: float
    unrealised_pnl: float
    fees: float
    turnover_notional: float


class PortfolioBenchmarkComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    benchmark: str
    total_return: float
    annualised_return: float
    excess_return: float
    tracking_difference: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    maximum_drawdown: float
    recovery_time_bars: int | None
    turnover_difference: float
    cost_difference: float
    downside_risk_difference: float


class RejectedPortfolioOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    order: SimulatedOrder
    reasons: tuple[str, ...]


class PortfolioBacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str
    universe: UniverseDefinition
    start: datetime
    end: datetime
    starting_capital: float
    final_equity: float
    adjustment_policy: AdjustmentPolicy
    costs: CostAssumptions
    metrics: PortfolioMetrics
    benchmarks: tuple[PortfolioBenchmarkComparison, ...]
    fills: tuple[SimulatedFill, ...]
    rejected_orders: tuple[RejectedPortfolioOrder, ...]
    trades: tuple[Trade, ...]
    equity_curve: tuple[PortfolioEquityPoint, ...]
    final_positions: dict[str, PortfolioPosition]
    strategy_attribution: tuple[PortfolioAttribution, ...]
    asset_attribution: tuple[PortfolioAttribution, ...]
    asset_class_attribution: tuple[PortfolioAttribution, ...]
    allocation_method: str
    execution_assumption: str = "signals at common bar close; earliest fill at next common bar open"
