"""Typed, closed-by-default configuration for the Phase 3 paper observatory."""

from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ForwardProviderConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str = "yahoo"
    enabled: bool = False
    read_only: bool = True
    requires_secret: bool = False

    @model_validator(mode="after")
    def require_credential_free_read_only_provider(self) -> "ForwardProviderConfiguration":
        if not self.read_only or self.requires_secret:
            raise ValueError("Phase 3 current-data providers must be credential-free/read-only")
        return self


class ForwardOperationsConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_root: Path = Path("data/forward_evidence")
    lease_ttl: timedelta = timedelta(minutes=15)
    freshness_tolerance: timedelta = timedelta(hours=36)
    portfolio_id: str = "phase3-forward-paper"
    maximum_trials: int = Field(default=8, ge=1, le=100)


class ReplayConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    random_seed: int = Field(default=1729, ge=0)
    source_dataset_id: str = "phase2-yahoo-demo-7e23dd823599693e"
    report_path: Path = Path("reports/phase3_replay_report.json")


class Phase3Configuration(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ForwardProviderConfiguration = Field(default_factory=ForwardProviderConfiguration)
    operations: ForwardOperationsConfiguration = Field(
        default_factory=ForwardOperationsConfiguration
    )
    replay: ReplayConfiguration = Field(default_factory=ReplayConfiguration)
