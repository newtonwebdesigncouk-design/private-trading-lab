"""Normalised-enough first-phase persistence tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class StrategyRow(Base):
    __tablename__ = "strategies"

    version_key: Mapped[str] = mapped_column(String(180), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32), index=True)
    specification: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BacktestResultRow(Base):
    __tablename__ = "backtest_results"

    result_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    strategy_version: Mapped[str] = mapped_column(ForeignKey("strategies.version_key"), index=True)
    dataset_id: Mapped[str] = mapped_column(String(256), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    costs: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    benchmark: Mapped[dict[str, Any]] = mapped_column(JSON)
    final_equity: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExperimentRow(Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    strategy_version: Mapped[str] = mapped_column(String(180), index=True)
    dataset_version: Mapped[str] = mapped_column(String(256))
    instruments: Mapped[list[str]] = mapped_column(JSON)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    transaction_cost_assumptions: Mapped[dict[str, Any]] = mapped_column(JSON)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    code_version: Mapped[str] = mapped_column(String(64))
    random_seed: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    validation_result: Mapped[str] = mapped_column(String(64))
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    universe_version: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    regime: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lifecycle_state: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    benchmark_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperAuditRow(Base):
    __tablename__ = "paper_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DatasetManifestRow(Base):
    __tablename__ = "dataset_manifests"

    dataset_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    provider: Mapped[str] = mapped_column(String(128), index=True)
    artifact_root: Mapped[str] = mapped_column(Text)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UniverseRow(Base):
    __tablename__ = "research_universes"

    version_key: Mapped[str] = mapped_column(String(180), primary_key=True)
    universe_id: Mapped[str] = mapped_column(String(128), index=True)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchBatchRow(Base):
    __tablename__ = "research_batches"

    batch_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(256), index=True)
    universe_version: Mapped[str] = mapped_column(String(180), index=True)
    candidate_count: Mapped[int] = mapped_column(Integer)
    retained_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    diagnostic: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RegimeLabelRow(Base):
    __tablename__ = "regime_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(256), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    label: Mapped[str] = mapped_column(String(128), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class PaperAccountRow(Base):
    __tablename__ = "paper_accounts"

    account_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    starting_cash: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    positions: Mapped[dict[str, Any]] = mapped_column(JSON)
    pending_orders: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    realised_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    fees_paid: Mapped[float] = mapped_column(Float, default=0.0)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    last_cycle_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperCycleRow(Base):
    __tablename__ = "paper_cycles"

    cycle_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("paper_accounts.account_id"), index=True)
    dataset_id: Mapped[str] = mapped_column(String(256), index=True)
    market_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaperOrderRow(Base):
    __tablename__ = "paper_orders"

    order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("paper_accounts.account_id"), index=True)
    cycle_id: Mapped[str] = mapped_column(ForeignKey("paper_cycles.cycle_id"), index=True)
    strategy_version: Mapped[str] = mapped_column(String(180), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperFillRow(Base):
    __tablename__ = "paper_fills"

    fill_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("paper_accounts.account_id"), index=True)
    cycle_id: Mapped[str] = mapped_column(ForeignKey("paper_cycles.cycle_id"), index=True)
    strategy_version: Mapped[str] = mapped_column(String(180), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PaperPortfolioSnapshotRow(Base):
    __tablename__ = "paper_portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("paper_accounts.account_id"), index=True)
    cycle_id: Mapped[str] = mapped_column(ForeignKey("paper_cycles.cycle_id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    account: Mapped[dict[str, Any]] = mapped_column(JSON)
