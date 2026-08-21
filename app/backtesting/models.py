"""Backtest configuration, accounting records and reports."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.market import Asset
from app.models.strategy import StrategySpec


class CostAssumptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    commission_bps: float = Field(default=2.0, ge=0)
    fixed_fee: float = Field(default=0.25, ge=0)
    minimum_commission: float = Field(default=0.25, ge=0)
    spread_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=3.0, ge=0)


class BacktestConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    starting_capital: float = Field(default=100_000.0, gt=0)
    position_fraction: float = Field(default=0.90, gt=0, le=1)
    annual_periods: int = Field(default=252, gt=0)
    costs: CostAssumptions = Field(default_factory=CostAssumptions)


class SimulatedOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    strategy_version: str
    asset: Asset
    side: OrderSide
    order_type: OrderType
    quantity: float = Field(gt=0)
    decision_timestamp: datetime
    limit_price: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_limit_price(self) -> "SimulatedOrder":
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        return self


class SimulatedFill(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    strategy_version: str
    asset: Asset
    timestamp: datetime
    side: OrderSide
    quantity: float
    reference_price: float
    fill_price: float
    notional: float
    fee: float
    slippage_cost: float
    status: OrderStatus = OrderStatus.FILLED


class Trade(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: str
    strategy_version: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    quantity: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    net_pnl: float
    fees: float


class EquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    cash: float
    position_quantity: float
    market_value: float
    equity: float
    realised_pnl: float
    unrealised_pnl: float
    drawdown: float


class PerformanceMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_return: float
    annualised_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    maximum_drawdown: float
    recovery_time_bars: int | None
    win_rate: float
    loss_rate: float
    average_winner: float
    average_loser: float
    profit_factor: float
    expectancy: float
    number_of_trades: int
    turnover: float
    exposure: float
    fees_paid: float
    slippage_cost: float


class BenchmarkComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    benchmark_symbol: str
    strategy_return: float
    benchmark_return: float
    excess_return: float
    strategy_drawdown: float
    benchmark_drawdown: float
    relative_drawdown: float
    strategy_volatility: float
    benchmark_volatility: float
    volatility_difference: float
    strategy_sharpe: float
    benchmark_sharpe: float
    risk_adjusted_advantage: float


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: StrategySpec
    dataset_id: str
    start: datetime
    end: datetime
    starting_capital: float
    final_equity: float
    costs: CostAssumptions
    metrics: PerformanceMetrics
    benchmark: BenchmarkComparison
    fills: tuple[SimulatedFill, ...]
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityPoint, ...]
    execution_assumption: str = "signal at bar close; earliest fill at next bar open"
