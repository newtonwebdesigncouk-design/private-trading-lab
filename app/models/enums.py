"""Closed enums keep unsafe or unsupported states unrepresentable."""

from enum import StrEnum


class AssetClass(StrEnum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    CRYPTOCURRENCY = "CRYPTOCURRENCY"
    FOREX = "FOREX"
    INDEX = "INDEX"


class TradingMode(StrEnum):
    """The complete set of execution modes supported in version 1."""

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"


class StrategyState(StrEnum):
    CREATED = "CREATED"
    BACKTESTING = "BACKTESTING"
    REJECTED = "REJECTED"
    VALIDATION = "VALIDATION"
    PAPER_ELIGIBLE = "PAPER_ELIGIBLE"
    PAPER_TRADING = "PAPER_TRADING"
    QUALIFIED = "QUALIFIED"
    RETIRED = "RETIRED"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CorporateActionType(StrEnum):
    STOCK_SPLIT = "STOCK_SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"


class AdjustmentPolicy(StrEnum):
    """Explicit policies prevent price and cash-return double counting."""

    UNADJUSTED_WITH_ACTIONS = "UNADJUSTED_WITH_ACTIONS"
    SPLIT_ADJUSTED_WITH_CASH_DIVIDENDS = "SPLIT_ADJUSTED_WITH_CASH_DIVIDENDS"
    TOTAL_RETURN_ADJUSTED = "TOTAL_RETURN_ADJUSTED"


class ForwardTrialState(StrEnum):
    """Paper-observation governance states; none authorises external execution."""

    READY_FOR_FORWARD = "READY_FOR_FORWARD"
    OBSERVING = "OBSERVING"
    PAUSED_DATA_QUALITY = "PAUSED_DATA_QUALITY"
    PAUSED_RISK = "PAUSED_RISK"
    FAILED_FORWARD = "FAILED_FORWARD"
    QUALIFIED_FORWARD = "QUALIFIED_FORWARD"
    RETIRED = "RETIRED"


class ObservationProvenance(StrEnum):
    """Evidence provenance is independent of the closed execution-mode enum."""

    GENUINE_FORWARD = "GENUINE_FORWARD"
    REPLAY = "REPLAY"


class ForwardCycleStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


class DegradationSeverity(StrEnum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    PAUSE = "PAUSE"
    FAIL = "FAIL"
