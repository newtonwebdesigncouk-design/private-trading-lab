"""Reproducible experiment metadata."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    strategy_version: str
    dataset_version: str
    instruments: tuple[str, ...]
    period_start: datetime
    period_end: datetime
    transaction_cost_assumptions: dict[str, float]
    parameters: dict[str, float | int | str | bool]
    code_version: str
    random_seed: int
    metrics: dict[str, Any]
    validation_result: str
    rejection_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("period_start", "period_end", "created_at")
    @classmethod
    def normalise_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
