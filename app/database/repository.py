"""Persistence boundary for reproducible research and paper audit events."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from app.backtesting.models import BacktestResult
from app.data.models import DatasetManifest
from app.database.tables import (
    BacktestResultRow,
    DatasetManifestRow,
    ExperimentRow,
    PaperAuditRow,
    RegimeLabelRow,
    ResearchBatchRow,
    StrategyRow,
    UniverseRow,
)
from app.models.strategy import StrategySpec
from app.research.batch import BatchResearchResult
from app.research.experiments import ExperimentRecord
from app.universe import UniverseDefinition
from app.validation.regimes import RegimeObservation


class ExperimentQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_version: str | None = None
    dataset_version: str | None = None
    universe_version: str | None = None
    instrument: str | None = None
    regime: str | None = None
    lifecycle_state: str | None = None
    minimum_score: float | None = None
    maximum_score: float | None = None
    benchmark_outcome: str | None = None
    limit: int = 100


class LaboratoryRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def save_strategy(self, strategy: StrategySpec) -> None:
        with self._sessions.begin() as session:
            if session.get(StrategyRow, strategy.version_key) is not None:
                raise ValueError("strategy versions are immutable once persisted")
            session.add(
                StrategyRow(
                    version_key=strategy.version_key,
                    strategy_id=strategy.strategy_id,
                    version=strategy.version,
                    state=strategy.state.value,
                    specification=strategy.model_dump(mode="json"),
                    created_at=strategy.created_at,
                )
            )

    def save_backtest(self, result: BacktestResult) -> str:
        raw = f"{result.strategy.version_key}|{result.dataset_id}|{result.start}|{result.end}"
        result_id = hashlib.sha256(raw.encode()).hexdigest()
        with self._sessions.begin() as session:
            session.add(
                BacktestResultRow(
                    result_id=result_id,
                    strategy_version=result.strategy.version_key,
                    dataset_id=result.dataset_id,
                    period_start=result.start,
                    period_end=result.end,
                    costs=result.costs.model_dump(mode="json"),
                    metrics=result.metrics.model_dump(mode="json"),
                    benchmark=result.benchmark.model_dump(mode="json"),
                    final_equity=result.final_equity,
                    created_at=datetime.now(UTC),
                )
            )
        return result_id

    def save_experiment(self, experiment: ExperimentRecord) -> None:
        with self._sessions.begin() as session:
            session.add(ExperimentRow(**experiment.model_dump(mode="python")))

    def save_dataset_manifest(self, manifest: DatasetManifest, artifact_root: Path) -> None:
        with self._sessions.begin() as session:
            if session.get(DatasetManifestRow, manifest.dataset_id) is not None:
                raise ValueError("dataset manifests are immutable once persisted")
            session.add(
                DatasetManifestRow(
                    dataset_id=manifest.dataset_id,
                    provider=manifest.provider,
                    artifact_root=str(artifact_root),
                    manifest=manifest.model_dump(mode="json"),
                    ingested_at=manifest.ingested_at,
                )
            )

    def save_universe(self, universe: UniverseDefinition) -> None:
        with self._sessions.begin() as session:
            if session.get(UniverseRow, universe.version_key) is not None:
                raise ValueError("universe versions are immutable once persisted")
            session.add(
                UniverseRow(
                    version_key=universe.version_key,
                    universe_id=universe.universe_id,
                    definition=universe.model_dump(mode="json"),
                    created_at=datetime.now(UTC),
                )
            )

    def save_research_batch(self, batch: BatchResearchResult) -> None:
        retained = len(batch.selected_candidate_versions)
        with self._sessions.begin() as session:
            if session.get(ResearchBatchRow, batch.batch_id) is not None:
                raise ValueError("research batches are immutable once persisted")
            session.add(
                ResearchBatchRow(
                    batch_id=batch.batch_id,
                    dataset_id=batch.dataset_id,
                    universe_version=batch.universe_version,
                    candidate_count=batch.candidate_count,
                    retained_count=retained,
                    rejected_count=batch.candidate_count - retained,
                    diagnostic=batch.multiple_testing.model_dump(mode="json"),
                    result=batch.model_dump(mode="json"),
                    created_at=datetime.now(UTC),
                )
            )

    def save_regime_labels(
        self,
        dataset_id: str,
        symbol: str,
        observations: tuple[RegimeObservation, ...],
    ) -> None:
        with self._sessions.begin() as session:
            for observation in observations:
                session.add(
                    RegimeLabelRow(
                        dataset_id=dataset_id,
                        symbol=symbol,
                        timestamp=observation.timestamp,
                        label=observation.label,
                        metadata_json=observation.model_dump(mode="json"),
                    )
                )

    def record(self, event_type: str, payload: dict[str, Any], timestamp: datetime) -> None:
        with self._sessions.begin() as session:
            session.add(
                PaperAuditRow(event_type=event_type, payload=payload, occurred_at=timestamp)
            )

    def recent_experiments(self, limit: int = 20) -> tuple[ExperimentRecord, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ExperimentRow).order_by(ExperimentRow.created_at.desc()).limit(limit)
            ).all()
            return tuple(
                ExperimentRecord.model_validate(
                    {
                        "experiment_id": row.experiment_id,
                        "strategy_version": row.strategy_version,
                        "dataset_version": row.dataset_version,
                        "instruments": tuple(row.instruments),
                        "period_start": row.period_start,
                        "period_end": row.period_end,
                        "transaction_cost_assumptions": row.transaction_cost_assumptions,
                        "parameters": row.parameters,
                        "code_version": row.code_version,
                        "random_seed": row.random_seed,
                        "metrics": row.metrics,
                        "validation_result": row.validation_result,
                        "rejection_reason": row.rejection_reason,
                        "universe_version": row.universe_version,
                        "regime": row.regime,
                        "lifecycle_state": row.lifecycle_state,
                        "score": row.score,
                        "benchmark_outcome": row.benchmark_outcome,
                        "candidate_count": row.candidate_count or 1,
                        "created_at": row.created_at,
                    }
                )
                for row in rows
            )

    def search_experiments(self, query: ExperimentQuery) -> tuple[ExperimentRecord, ...]:
        statement: Select[tuple[ExperimentRow]] = select(ExperimentRow)
        if query.strategy_version is not None:
            statement = statement.where(ExperimentRow.strategy_version == query.strategy_version)
        if query.dataset_version is not None:
            statement = statement.where(ExperimentRow.dataset_version == query.dataset_version)
        if query.universe_version is not None:
            statement = statement.where(ExperimentRow.universe_version == query.universe_version)
        if query.instrument is not None:
            statement = statement.where(ExperimentRow.instruments.contains([query.instrument]))
        if query.regime is not None:
            statement = statement.where(ExperimentRow.regime == query.regime)
        if query.lifecycle_state is not None:
            statement = statement.where(ExperimentRow.lifecycle_state == query.lifecycle_state)
        if query.minimum_score is not None:
            statement = statement.where(ExperimentRow.score >= query.minimum_score)
        if query.maximum_score is not None:
            statement = statement.where(ExperimentRow.score <= query.maximum_score)
        if query.benchmark_outcome is not None:
            statement = statement.where(ExperimentRow.benchmark_outcome == query.benchmark_outcome)
        with self._sessions() as session:
            rows = session.scalars(
                statement.order_by(ExperimentRow.created_at.desc()).limit(query.limit)
            ).all()
        return tuple(
            ExperimentRecord.model_validate(
                {
                    column.name: getattr(row, column.name)
                    for column in ExperimentRow.__table__.columns
                    if column.name != "candidate_count" or getattr(row, column.name) is not None
                }
            )
            for row in rows
        )
