"""Portfolio-level controls that strategies cannot modify."""

from collections.abc import Mapping
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

    @field_validator("current_asset_class_exposure", mode="after")
    @classmethod
    def freeze_exposure(cls, value: Mapping[AssetClass, float]) -> Mapping[AssetClass, float]:
        return MappingProxyType(dict(value))

    @field_serializer("current_asset_class_exposure")
    def serialise_exposure(self, value: Mapping[AssetClass, float]) -> dict[str, float]:
        return {key.value: exposure for key, exposure in value.items()}


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
            if requested_fraction > self._limits.maximum_position_percentage:
                reasons.append("maximum position percentage exceeded")
            if (
                context.current_portfolio_exposure + requested_fraction
                > self._limits.maximum_portfolio_exposure
            ):
                reasons.append("maximum portfolio exposure exceeded")
            class_exposure = context.current_asset_class_exposure.get(asset_class, 0.0)
            if class_exposure + requested_fraction > self._limits.maximum_asset_class_exposure:
                reasons.append("maximum asset-class exposure exceeded")
            is_new = symbol not in context.open_position_symbols
            if (
                is_new
                and len(context.open_position_symbols) >= self._limits.maximum_concurrent_positions
            ):
                reasons.append("maximum concurrent positions reached")
        return RiskDecision(allowed=not reasons, reasons=tuple(reasons))
