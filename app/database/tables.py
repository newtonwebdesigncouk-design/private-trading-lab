"""Normalised-enough first-phase persistence tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperAuditRow(Base):
    __tablename__ = "paper_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
