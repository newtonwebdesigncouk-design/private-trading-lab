"""Phase 2 immutable data, research catalogue, regimes, and persistent paper state.

Revision ID: 0002_phase_2
Revises: 0001_phase_1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase_2"
down_revision: str | None = "0001_phase_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name, type_ in (
        ("universe_version", sa.String(length=180)),
        ("regime", sa.String(length=128)),
        ("lifecycle_state", sa.String(length=64)),
        ("score", sa.Float()),
        ("benchmark_outcome", sa.String(length=64)),
        ("candidate_count", sa.Integer()),
    ):
        op.add_column("experiments", sa.Column(name, type_, nullable=True))
    op.create_table(
        "dataset_manifests",
        sa.Column("dataset_id", sa.String(256), primary_key=True),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("artifact_root", sa.Text(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_universes",
        sa.Column("version_key", sa.String(180), primary_key=True),
        sa.Column("universe_id", sa.String(128), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_batches",
        sa.Column("batch_id", sa.String(128), primary_key=True),
        sa.Column("dataset_id", sa.String(256), nullable=False),
        sa.Column("universe_version", sa.String(180), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("retained_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("diagnostic", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "regime_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dataset_id", sa.String(256), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("dataset_id", "symbol", "timestamp"),
    )
    op.create_table(
        "paper_accounts",
        sa.Column("account_id", sa.String(128), primary_key=True),
        sa.Column("starting_cash", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("positions", sa.JSON(), nullable=False),
        sa.Column("pending_orders", sa.JSON(), nullable=False),
        sa.Column("realised_pnl", sa.Float(), nullable=False),
        sa.Column("fees_paid", sa.Float(), nullable=False),
        sa.Column("kill_switch", sa.Boolean(), nullable=False),
        sa.Column("last_cycle_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_cycles",
        sa.Column("cycle_id", sa.String(128), primary_key=True),
        sa.Column("account_id", sa.String(128), sa.ForeignKey("paper_accounts.account_id")),
        sa.Column("dataset_id", sa.String(256), nullable=False),
        sa.Column("market_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "paper_orders",
        sa.Column("order_id", sa.String(128), primary_key=True),
        sa.Column("account_id", sa.String(128), sa.ForeignKey("paper_accounts.account_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("paper_cycles.cycle_id")),
        sa.Column("strategy_version", sa.String(180), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_fills",
        sa.Column("fill_id", sa.String(128), primary_key=True),
        sa.Column("order_id", sa.String(128), nullable=False),
        sa.Column("account_id", sa.String(128), sa.ForeignKey("paper_accounts.account_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("paper_cycles.cycle_id")),
        sa.Column("strategy_version", sa.String(180), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(128), sa.ForeignKey("paper_accounts.account_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("paper_cycles.cycle_id")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "paper_portfolio_snapshots",
        "paper_fills",
        "paper_orders",
        "paper_cycles",
        "paper_accounts",
        "regime_labels",
        "research_batches",
        "research_universes",
        "dataset_manifests",
    ):
        op.drop_table(table)
    for column in (
        "candidate_count",
        "benchmark_outcome",
        "score",
        "lifecycle_state",
        "regime",
        "universe_version",
    ):
        op.drop_column("experiments", column)
