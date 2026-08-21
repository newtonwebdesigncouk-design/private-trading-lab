"""Phase 3 frozen forward trials, evidence, governance, and audit history.

Revision ID: 0003_phase_3
Revises: 0002_phase_2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase_3"
down_revision: str | None = "0002_phase_2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forward_trials",
        sa.Column("trial_id", sa.String(128), primary_key=True),
        sa.Column("portfolio_id", sa.String(128), nullable=False, index=True),
        sa.Column("strategy_version", sa.String(180), nullable=False, index=True),
        sa.Column("configuration_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("provenance", sa.String(32), nullable=False, index=True),
        sa.Column("state", sa.String(64), nullable=False, index=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("failed_evaluations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("latest_observation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "forward_evidence_manifests",
        sa.Column("manifest_id", sa.String(128), primary_key=True),
        sa.Column("stream_id", sa.String(128), nullable=False, index=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("provenance", sa.String(32), nullable=False, index=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.UniqueConstraint("stream_id", "sequence"),
    )
    op.create_table(
        "forward_cycle_leases",
        sa.Column("lease_key", sa.String(128), primary_key=True),
        sa.Column("owner", sa.String(128), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("cycle_id", sa.String(128), nullable=True),
    )
    op.create_table(
        "forward_cycles",
        sa.Column("cycle_id", sa.String(128), primary_key=True),
        sa.Column("portfolio_id", sa.String(128), nullable=False, index=True),
        sa.Column("evidence_manifest_id", sa.String(128), nullable=False, index=True),
        sa.Column("provenance", sa.String(32), nullable=False, index=True),
        sa.Column("market_timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("lease_owner", sa.String(128), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "forward_portfolios",
        sa.Column("portfolio_id", sa.String(128), primary_key=True),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("provenance", sa.String(32), nullable=False, index=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "forward_observations",
        sa.Column("observation_id", sa.String(128), primary_key=True),
        sa.Column("trial_id", sa.String(128), sa.ForeignKey("forward_trials.trial_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("forward_cycles.cycle_id")),
        sa.Column("evidence_manifest_id", sa.String(128), nullable=False),
        sa.Column("provenance", sa.String(32), nullable=False, index=True),
        sa.Column("symbol", sa.String(64), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("trial_id", "symbol", "timestamp", "provenance"),
    )
    op.create_table(
        "forward_signals",
        sa.Column("signal_id", sa.String(128), primary_key=True),
        sa.Column("trial_id", sa.String(128), sa.ForeignKey("forward_trials.trial_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("forward_cycles.cycle_id")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "forward_orders",
        sa.Column("order_id", sa.String(128), primary_key=True),
        sa.Column("trial_id", sa.String(128), sa.ForeignKey("forward_trials.trial_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("forward_cycles.cycle_id")),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "forward_fills",
        sa.Column("fill_id", sa.String(128), primary_key=True),
        sa.Column("order_id", sa.String(128), nullable=False, index=True),
        sa.Column("trial_id", sa.String(128), sa.ForeignKey("forward_trials.trial_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("forward_cycles.cycle_id")),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_table(
        "forward_benchmark_snapshots",
        sa.Column("snapshot_id", sa.String(128), primary_key=True),
        sa.Column("trial_id", sa.String(128), sa.ForeignKey("forward_trials.trial_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("forward_cycles.cycle_id")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("performance", sa.JSON(), nullable=False),
    )
    op.create_table(
        "forward_portfolio_snapshots",
        sa.Column("snapshot_id", sa.String(128), primary_key=True),
        sa.Column("portfolio_id", sa.String(128), nullable=False, index=True),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("forward_cycles.cycle_id")),
        sa.Column("provenance", sa.String(32), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "forward_lifecycle_decisions",
        sa.Column("decision_id", sa.String(128), primary_key=True),
        sa.Column("trial_id", sa.String(128), sa.ForeignKey("forward_trials.trial_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("forward_cycles.cycle_id")),
        sa.Column("previous_state", sa.String(64), nullable=False),
        sa.Column("new_state", sa.String(64), nullable=False, index=True),
        sa.Column("rule_id", sa.String(128), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "forward_data_quality_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("cycle_id", sa.String(128), nullable=False, index=True),
        sa.Column("trial_id", sa.String(128), nullable=True, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("severity", sa.String(32), nullable=False, index=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "forward_degradation_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("trial_id", sa.String(128), sa.ForeignKey("forward_trials.trial_id")),
        sa.Column("cycle_id", sa.String(128), sa.ForeignKey("forward_cycles.cycle_id")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("severity", sa.String(32), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "forward_audit_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("cycle_id", sa.String(128), nullable=False, index=True),
        sa.Column("trial_id", sa.String(128), nullable=True, index=True),
        sa.Column("event_type", sa.String(128), nullable=False, index=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "forward_audit_events",
        "forward_degradation_events",
        "forward_data_quality_events",
        "forward_lifecycle_decisions",
        "forward_portfolio_snapshots",
        "forward_benchmark_snapshots",
        "forward_fills",
        "forward_orders",
        "forward_signals",
        "forward_observations",
        "forward_portfolios",
        "forward_cycles",
        "forward_cycle_leases",
        "forward_evidence_manifests",
        "forward_trials",
    ):
        op.drop_table(table)
