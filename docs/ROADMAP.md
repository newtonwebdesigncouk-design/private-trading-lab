# Roadmap

## Phase 1 foundation — delivered here

Canonical data/spec models, synthetic/cached data, four reference strategies, cost-aware next-bar
backtesting, analytics, benchmark comparison, chronological validation, sensitivity, regime labels,
risk scoring, independent risk controls, audited paper simulation, bounded research, SQLAlchemy/
Alembic persistence, local API, tests, CI, Docker, and safety scanning.

## Recommended next milestone

Add a read-only historical-data adapter and a dataset catalogue with content hashes, adjustment/
corporate-action provenance, exchange calendars, missing-bar diagnostics, and golden datasets. Then
run longer walk-forward/out-of-sample studies across multiple instruments per asset class. Keep all
execution simulated.

## Later research milestones

1. Multi-asset portfolio backtesting, correlation/concentration constraints, and benchmark mapping.
2. Volume participation, partial fills, latency, richer corporate actions, and foreign-exchange
   conversion.
3. Persistent paper replay scheduling and a small local visual dashboard.
4. Statistical multiple-testing controls, bootstrap confidence intervals, and deflated Sharpe.
5. Read-only live market-data observation after a separate privacy/security review.

Real-money order submission, leverage, margin, derivatives, short borrowing, money movement, and
self-modifying risk controls are explicitly outside this roadmap until separately reviewed.
