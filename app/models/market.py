"""Canonical, provider-neutral market data models."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AssetClass


class Asset(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=32)
    asset_class: AssetClass
    currency: str = Field(default="USD", min_length=3, max_length=8)
    exchange: str = Field(default="SYNTHETIC", min_length=1, max_length=32)

    @property
    def cache_key(self) -> str:
        return f"{self.asset_class.value}-{self.exchange}-{self.symbol}".lower()


class MarketBar(BaseModel):
    """A bar timestamp denotes the bar close, when the values become knowable."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    adjusted_close: float | None = Field(default=None, gt=0)
    volume: float = Field(ge=0)
    asset: Asset
    source: str = Field(min_length=1)
    interval: str = Field(min_length=1)
    dividend: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_bar(self) -> "MarketBar":
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC values are inconsistent")
        if self.high < self.low:
            raise ValueError("high must be greater than or equal to low")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return self

    @property
    def effective_close(self) -> float:
        return self.adjusted_close if self.adjusted_close is not None else self.close

    @classmethod
    def utc_timestamp(cls, **values: object) -> "MarketBar":
        timestamp = values.get("timestamp")
        if isinstance(timestamp, datetime) and timestamp.tzinfo is None:
            values["timestamp"] = timestamp.replace(tzinfo=UTC)
        return cls.model_validate(values)
