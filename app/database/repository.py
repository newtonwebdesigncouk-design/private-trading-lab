"""Persistence boundary for reproducible research and paper audit events."""

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.backtesting.models import BacktestResult
from app.database.tables import BacktestResultRow, ExperimentRow, PaperAuditRow, StrategyRow
from app.models.strategy import StrategySpec
from app.research.experiments import ExperimentRecord


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
                        "created_at": row.created_at,
                    }
                )
                for row in rows
            )
