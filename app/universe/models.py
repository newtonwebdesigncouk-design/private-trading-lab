"""Explicit universes avoid pretending current constituents existed historically."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AssetClass
from app.models.market import Asset


class UniverseInstrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Asset
    category: str
    inclusion_reason: str
    benchmark_symbol: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class UniverseDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    universe_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    instruments: tuple[UniverseInstrument, ...]
    quote_currency: str = "USD"
    provider: str
    survivorship_note: str = (
        "Owner-configured liquid instrument list; historical membership is not reconstructed."
    )

    @model_validator(mode="after")
    def validate_instruments(self) -> "UniverseDefinition":
        if not self.instruments:
            raise ValueError("a universe requires at least one instrument")
        symbols = [item.asset.symbol for item in self.instruments]
        if len(symbols) != len(set(symbols)):
            raise ValueError("universe instrument symbols must be unique")
        return self

    @property
    def version_key(self) -> str:
        return f"{self.universe_id}:v{self.version}"

    @property
    def asset_classes(self) -> frozenset[AssetClass]:
        return frozenset(item.asset.asset_class for item in self.instruments)

    @property
    def assets(self) -> tuple[Asset, ...]:
        return tuple(item.asset for item in self.instruments)
