"""Provider metadata, raw observations, diagnostics, and immutable dataset manifests."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AdjustmentPolicy, AssetClass, CorporateActionType
from app.models.market import Asset, MarketBar


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_classes: frozenset[AssetClass]
    intervals: tuple[str, ...]
    corporate_actions: bool = False
    requires_secret: bool = False
    read_only: bool = True


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    source_url: str
    version: str
    capabilities: ProviderCapabilities
    configuration: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AssetMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Asset
    provider_symbol: str
    timezone: str
    supported_intervals: tuple[str, ...]
    first_available: datetime | None = None
    last_available: datetime | None = None


class RawMarketBar(BaseModel):
    """Permissive transport model; canonical validation happens during normalisation."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None = None
    volume: float = 0.0
    dividend: float = 0.0


class NormalisationEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    timestamp: datetime | None = None
    detail: str


class DataQualityDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_rows: int = 0
    output_rows: int = 0
    duplicate_rows: int = 0
    invalid_rows: int = 0
    out_of_order_rows: int = 0
    missing_expected_timestamps: tuple[datetime, ...] = ()
    partial_response: bool = False
    stale: bool = False
    events: tuple[NormalisationEvent, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.output_rows > 0 and self.invalid_rows == 0 and not self.partial_response


class CorporateAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Asset
    effective_timestamp: datetime
    action_type: CorporateActionType
    split_ratio: float | None = Field(default=None, gt=0)
    cash_amount: float | None = Field(default=None, ge=0)
    currency: str = "USD"
    source: str
    source_reference: str | None = None

    @model_validator(mode="after")
    def require_action_value(self) -> "CorporateAction":
        if self.action_type is CorporateActionType.STOCK_SPLIT and self.split_ratio is None:
            raise ValueError("stock split requires split_ratio")
        if self.action_type is CorporateActionType.CASH_DIVIDEND and self.cash_amount is None:
            raise ValueError("cash dividend requires cash_amount")
        return self


class HistoricalDataBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    provider_version: str
    asset: Asset
    interval: str
    requested_start: datetime
    requested_end: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bars: tuple[MarketBar, ...]
    corporate_actions: tuple[CorporateAction, ...] = ()
    raw_checksum: str
    diagnostics: DataQualityDiagnostics
    adjustment_policy: AdjustmentPolicy
    provider_configuration: dict[str, str | int | float | bool] = Field(default_factory=dict)


class InstrumentSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Asset
    rows: int
    actual_start: datetime
    actual_end: datetime
    raw_checksum: str
    canonical_checksum: str
    artifact: str
    corporate_action_rows: int = 0
    corporate_action_checksum: str | None = None
    corporate_action_artifact: str | None = None
    diagnostics: DataQualityDiagnostics


class DatasetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 2
    dataset_id: str
    dataset_version: str
    provider: str
    provider_version: str
    instruments: tuple[InstrumentSnapshot, ...]
    asset_classes: tuple[AssetClass, ...]
    interval: str
    requested_start: datetime
    requested_end: datetime
    actual_start: datetime
    actual_end: datetime
    timezone_normalization: str = "UTC"
    adjustment_policy: AdjustmentPolicy
    corporate_action_policy: str
    ingested_at: datetime
    provider_configuration: dict[str, str | int | float | bool]
    code_revision: str
    manifest_checksum: str

    @property
    def row_counts(self) -> dict[str, int]:
        return {item.asset.symbol: item.rows for item in self.instruments}

    def public_metadata(self) -> dict[str, Any]:
        """Return API-safe metadata; provider configuration is secret-free by construction."""
        return self.model_dump(mode="json")


class DatasetFreshness(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str
    latest_observation: datetime
    evaluated_at: datetime
    age_seconds: float = Field(ge=0)
    maximum_age_seconds: float = Field(gt=0)
    stale: bool
