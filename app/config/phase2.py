"""Typed owner/development configuration for the Phase 2 laboratory."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.backtesting.models import CostAssumptions
from app.risk import RiskLimits
from app.validation.qualification import QualificationRequirements


class ReadOnlyProviderConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "stooq"
    enabled: bool = True
    read_only: bool = True
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    maximum_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def require_read_only(self) -> "ReadOnlyProviderConfiguration":
        if not self.read_only:
            raise ValueError("Phase 2 providers must be read-only")
        return self


class DatasetConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_root: Path = Path("data/snapshots")
    maximum_staleness_hours: int = Field(default=36, ge=1)


class ResearchConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    maximum_candidates: int = Field(default=500, ge=1, le=10_000)
    false_discovery_rate: float = Field(default=0.05, gt=0, lt=1)
    random_seed: int = Field(default=1729, ge=0)


class PortfolioConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    allocator: str = "equal_weight"
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)


class PaperCycleConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    scheduler_interval_minutes: int = Field(default=1440, ge=1)
    freshness_tolerance_minutes: int = Field(default=2160, ge=1)
    account_id: str = "phase2-paper"


class Phase2Configuration(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ReadOnlyProviderConfiguration = Field(default_factory=ReadOnlyProviderConfiguration)
    datasets: DatasetConfiguration = Field(default_factory=DatasetConfiguration)
    research: ResearchConfiguration = Field(default_factory=ResearchConfiguration)
    portfolio: PortfolioConfiguration = Field(default_factory=PortfolioConfiguration)
    qualification: QualificationRequirements = Field(default_factory=QualificationRequirements)
    paper: PaperCycleConfiguration = Field(default_factory=PaperCycleConfiguration)
