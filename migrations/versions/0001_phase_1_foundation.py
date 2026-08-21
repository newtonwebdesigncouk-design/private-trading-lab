"""Phase 1 strategy, results, experiments and paper audit tables.

Revision ID: 0001_phase_1
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase_1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("version_key", sa.String(length=180), nullable=False),
        sa.Column("strategy_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("specification", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version_key"),
    )
    op.create_index("ix_strategies_strategy_id", "strategies", ["strategy_id"])
    op.create_index("ix_strategies_state", "strategies", ["state"])
    op.create_table(
        "backtest_results",
        sa.Column("result_id", sa.String(length=128), nullable=False),
        sa.Column("strategy_version", sa.String(length=180), nullable=False),
        sa.Column("dataset_id", sa.String(length=256), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("costs", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("benchmark", sa.JSON(), nullable=False),
        sa.Column("final_equity", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["strategy_version"], ["strategies.version_key"]),
        sa.PrimaryKeyConstraint("result_id"),
    )
    op.create_index("ix_backtest_results_dataset_id", "backtest_results", ["dataset_id"])
    op.create_index(
        "ix_backtest_results_strategy_version", "backtest_results", ["strategy_version"]
    )
    op.create_table(
        "experiments",
        sa.Column("experiment_id", sa.String(length=128), nullable=False),
        sa.Column("strategy_version", sa.String(length=180), nullable=False),
        sa.Column("dataset_version", sa.String(length=256), nullable=False),
        sa.Column("instruments", sa.JSON(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transaction_cost_assumptions", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("code_version", sa.String(length=64), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("validation_result", sa.String(length=64), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("experiment_id"),
    )
    op.create_index("ix_experiments_strategy_version", "experiments", ["strategy_version"])
    op.create_table(
        "paper_audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_audit_events_event_type", "paper_audit_events", ["event_type"])
    op.create_index("ix_paper_audit_events_occurred_at", "paper_audit_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_table("paper_audit_events")
    op.drop_table("experiments")
    op.drop_table("backtest_results")
    op.drop_table("strategies")
