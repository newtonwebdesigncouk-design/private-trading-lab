"""Portfolio-level controls that strategies cannot modify."""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.models.enums import AssetClass, OrderSide


class RiskLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    maximum_position_percentage: float = Field(default=0.20, gt=0, le=1)
    maximum_asset_class_exposure: float = Field(default=0.60, gt=0, le=1)
    maximum_portfolio_exposure: float = Field(default=0.90, gt=0, le=1)
    maximum_daily_simulated_loss: float = Field(default=0.03, gt=0, le=1)
    maximum_weekly_simulated_loss: float = Field(default=0.07, gt=0, le=1)
    maximum_drawdown: float = Field(default=0.20, gt=0, le=1)
    maximum_concurrent_positions: int = Field(default=8, gt=0)
    maximum_trades_per_period: int = Field(default=20, gt=0)
    minimum_cash_reserve: float = Field(default=0.05, ge=0, lt=1)
    maximum_turnover_per_period: float = Field(default=1.50, gt=0)
    correlation_threshold: float = Field(default=0.85, ge=0, le=1)
    maximum_correlated_exposure: float = Field(default=0.40, gt=0, le=1)
    stale_after: timedelta = timedelta(minutes=5)
    abnormal_price_move: float = Field(default=0.20, gt=0)


class RiskContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    portfolio_equity: float = Field(gt=0)
    current_portfolio_exposure: float = Field(ge=0)
    current_asset_class_exposure: Mapping[AssetClass, float] = Field(default_factory=dict)
    open_position_symbols: frozenset[str] = frozenset()
    daily_return: float = 0.0
    weekly_return: float = 0.0
    current_drawdown: float = 0.0
    trades_in_period: int = 0
    market_timestamp: datetime
    evaluation_timestamp: datetime
    previous_price: float | None = Field(default=None, gt=0)
    cash_available: float | None = Field(default=None, ge=0)
    current_turnover: float = Field(default=0.0, ge=0)
    current_position_weights: Mapping[str, float] = Field(default_factory=dict)
    correlated_exposure: float = Field(default=0.0, ge=0)

    @field_validator("current_asset_class_exposure", mode="after")
    @classmethod
    def freeze_exposure(cls, value: Mapping[AssetClass, float]) -> Mapping[AssetClass, float]:
        return MappingProxyType(dict(value))

    @field_validator("current_position_weights", mode="after")
    @classmethod
    def freeze_position_weights(cls, value: Mapping[str, float]) -> Mapping[str, float]:
        return MappingProxyType(dict(value))

    @field_serializer("current_asset_class_exposure")
    def serialise_exposure(self, value: Mapping[AssetClass, float]) -> dict[str, float]:
        return {key.value: exposure for key, exposure in value.items()}

    @field_serializer("current_position_weights")
    def serialise_position_weights(self, value: Mapping[str, float]) -> dict[str, float]:
        return dict(value)


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reasons: tuple[str, ...]


class RiskEngine:
    """Evaluates requested exposure. Limits are frozen and exposed read-only."""

    def __init__(self, limits: RiskLimits | None = None, *, kill_switch: bool = False) -> None:
        self._limits = limits or RiskLimits()
        self._kill_switch = kill_switch

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    @property
    def kill_switch_engaged(self) -> bool:
        return self._kill_switch

    def evaluate(
        self,
        *,
        symbol: str,
        asset_class: AssetClass,
        side: OrderSide,
        requested_notional: float,
        requested_price: float,
        context: RiskContext,
    ) -> RiskDecision:
        reasons: list[str] = []
        requested_fraction = requested_notional / context.portfolio_equity
        if self._kill_switch:
            reasons.append("TRADING_KILL_SWITCH is engaged")
        if requested_notional <= 0 or requested_price <= 0:
            reasons.append("order notional and price must be positive")
        if context.evaluation_timestamp - context.market_timestamp > self._limits.stale_after:
            reasons.append("market data is stale")
        if context.market_timestamp > context.evaluation_timestamp:
            reasons.append("market data timestamp is in the future")
        if context.previous_price is not None:
            move = abs(requested_price / context.previous_price - 1.0)
            if move > self._limits.abnormal_price_move:
                reasons.append("abnormal price movement")
        if side is OrderSide.BUY:
            if context.daily_return <= -self._limits.maximum_daily_simulated_loss:
                reasons.append("maximum daily simulated loss reached")
            if context.weekly_return <= -self._limits.maximum_weekly_simulated_loss:
                reasons.append("maximum weekly simulated loss reached")
            if context.current_drawdown >= self._limits.maximum_drawdown:
                reasons.append("maximum drawdown reached")
            if context.trades_in_period >= self._limits.maximum_trades_per_period:
                reasons.append("maximum trades per period reached")
            final_position_weight = (
                context.current_position_weights.get(symbol, 0.0) + requested_fraction
            )
            if final_position_weight > self._limits.maximum_position_percentage:
                reasons.append("maximum position percentage exceeded")
            if (
                context.current_portfolio_exposure + requested_fraction
                > self._limits.maximum_portfolio_exposure
            ):
                reasons.append("maximum portfolio exposure exceeded")
            class_exposure = context.current_asset_class_exposure.get(asset_class, 0.0)
            if class_exposure + requested_fraction > self._limits.maximum_asset_class_exposure:
                reasons.append("maximum asset-class exposure exceeded")
            if (
                context.cash_available is not None
                and context.cash_available - requested_notional
                < context.portfolio_equity * self._limits.minimum_cash_reserve
            ):
                reasons.append("minimum cash reserve would be breached")
            if (
                context.current_turnover + requested_fraction
                > self._limits.maximum_turnover_per_period
            ):
                reasons.append("maximum turnover exceeded")
            if (
                context.correlated_exposure + requested_fraction
                > self._limits.maximum_correlated_exposure
            ):
                reasons.append("correlation-aware concentration limit exceeded")
            is_new = symbol not in context.open_position_symbols
            if (
                is_new
                and len(context.open_position_symbols) >= self._limits.maximum_concurrent_positions
            ):
                reasons.append("maximum concurrent positions reached")
        return RiskDecision(allowed=not reasons, reasons=tuple(reasons))


class PortfolioRiskStatistics(BaseModel):
    model_config = ConfigDict(frozen=True)

    rolling_volatility: dict[str, float]
    correlation_matrix: dict[str, dict[str, float]]
    portfolio_volatility: float
    risk_contribution: dict[str, float]


def calculate_portfolio_risk_statistics(
    return_history: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    *,
    annual_periods: int = 252,
) -> PortfolioRiskStatistics:
    """Explainable sample covariance analytics with aligned trailing observations."""
    symbols = tuple(sorted(set(return_history).intersection(weights)))
    if not symbols:
        return PortfolioRiskStatistics(
            rolling_volatility={},
            correlation_matrix={},
            portfolio_volatility=0.0,
            risk_contribution={},
        )
    length = min(len(return_history[symbol]) for symbol in symbols)
    if length < 2:
        zeros = {symbol: 0.0 for symbol in symbols}
        identity = {
            left: {right: 1.0 if left == right else 0.0 for right in symbols} for left in symbols
        }
        return PortfolioRiskStatistics(
            rolling_volatility=zeros,
            correlation_matrix=identity,
            portfolio_volatility=0.0,
            risk_contribution=zeros,
        )
    aligned = {symbol: tuple(return_history[symbol][-length:]) for symbol in symbols}
    means = {symbol: sum(aligned[symbol]) / length for symbol in symbols}
    covariance: dict[str, dict[str, float]] = {}
    for left in symbols:
        covariance[left] = {}
        for right in symbols:
            covariance[left][right] = sum(
                (aligned[left][index] - means[left]) * (aligned[right][index] - means[right])
                for index in range(length)
            ) / (length - 1)
    volatility = {
        symbol: math.sqrt(max(covariance[symbol][symbol], 0.0) * annual_periods)
        for symbol in symbols
    }
    correlations: dict[str, dict[str, float]] = {}
    for left in symbols:
        correlations[left] = {}
        for right in symbols:
            denominator = math.sqrt(
                max(covariance[left][left], 0.0) * max(covariance[right][right], 0.0)
            )
            correlations[left][right] = (
                covariance[left][right] / denominator if denominator else 0.0
            )
    variance = sum(
        weights[left] * weights[right] * covariance[left][right]
        for left in symbols
        for right in symbols
    )
    annualised_portfolio_volatility = math.sqrt(max(variance, 0.0) * annual_periods)
    contributions: dict[str, float] = {}
    if variance > 0:
        for symbol in symbols:
            marginal = sum(weights[other] * covariance[symbol][other] for other in symbols)
            contributions[symbol] = weights[symbol] * marginal / variance
    else:
        contributions = {symbol: 0.0 for symbol in symbols}
    return PortfolioRiskStatistics(
        rolling_volatility=volatility,
        correlation_matrix=correlations,
        portfolio_volatility=annualised_portfolio_volatility,
        risk_contribution=contributions,
    )
