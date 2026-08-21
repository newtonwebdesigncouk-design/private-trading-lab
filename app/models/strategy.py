"""Immutable, versioned and explainable strategy specifications."""

from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.models.enums import AssetClass, StrategyState


class IndicatorSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    parameters: Mapping[str, float | int] = Field(default_factory=dict)

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(cls, value: Mapping[str, float | int]) -> Mapping[str, float | int]:
        return MappingProxyType(dict(value))

    @field_serializer("parameters")
    def serialise_parameters(self, value: Mapping[str, object]) -> dict[str, object]:
        return dict(value)


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    name: str
    description: str
    asset_class: AssetClass
    permitted_assets: tuple[str, ...]
    timeframe: str
    indicators: tuple[IndicatorSpec, ...]
    entry_conditions: tuple[str, ...]
    exit_conditions: tuple[str, ...]
    stop_conditions: tuple[str, ...] = ()
    eligible_regimes: tuple[str, ...] = ()
    position_sizing_method: str = "fractional_equity"
    parameters: Mapping[str, float | int | str | bool] = Field(default_factory=dict)
    creation_method: str = "reference"
    creation_reason: str = "Reference strategy for engine validation"
    parent_strategy: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: StrategyState = StrategyState.CREATED

    @field_validator("permitted_assets")
    @classmethod
    def require_assets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one permitted asset is required")
        return value

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(
        cls, value: Mapping[str, float | int | str | bool]
    ) -> Mapping[str, float | int | str | bool]:
        return MappingProxyType(dict(value))

    @field_serializer("parameters")
    def serialise_parameters(self, value: Mapping[str, object]) -> dict[str, object]:
        return dict(value)

    @property
    def version_key(self) -> str:
        return f"{self.strategy_id}:v{self.version}"

    def derive(
        self,
        *,
        parameters: Mapping[str, float | int | str | bool],
        reason: str,
        creation_method: str = "bounded_parameter_search",
    ) -> "StrategySpec":
        data: dict[str, Any] = self.model_dump()
        data.update(
            version=self.version + 1,
            parameters=dict(parameters),
            creation_method=creation_method,
            creation_reason=reason,
            parent_strategy=self.version_key,
            created_at=datetime.now(UTC),
            state=StrategyState.CREATED,
        )
        return StrategySpec.model_validate(data)
