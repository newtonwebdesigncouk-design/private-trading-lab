# Roadmap

## Phase 1 foundation — delivered

Canonical models, synthetic data, four reference strategies, cost-aware next-bar backtesting,
analytics, passive comparison, chronological validation, independent risk controls, audited local
paper simulation, bounded research, SQLAlchemy/Alembic persistence, a local API, CI, and safety
scanning.

## Phase 2 real-data paper laboratory — delivered

Read-only Yahoo and Stooq historical adapters, canonical normalization, calendars, immutable
checksummed snapshots, corporate-action provenance, versioned universes, multi-asset portfolio
accounting, allocation methods, portfolio/correlation risk, asset and universe benchmarks,
hard-capped cross-instrument research, false-discovery diagnostics, point-in-time regimes, locked
holdouts, fixed qualification rules, persistent idempotent paper cycles, extended database/read
API, CLI workflows, a genuine historical demo, and stricter no-live scanning.

The Stooq adapter currently rejects the provider's browser proof-of-work response because satisfying
it would require an unapproved write-like request. Yahoo Chart is therefore the Phase 2 demo source.

## Recommended next milestone

Strengthen data realism without expanding execution scope:

1. Add a second stable, explicitly licensed, GET-only historical provider and cross-provider golden
   reconciliation tests.
2. Add exchange-specific holiday/early-close calendars and point-in-time constituent/delisting
   histories to reduce survivorship bias.
3. Model volume participation, partial fills, impact, latency, corporate-action revisions, and
   multi-currency valuation in simulation.
4. Add block/bootstrap confidence intervals and deflated-Sharpe or other dependence-aware
   multiple-testing diagnostics.
5. Operate the persistent paper lab over a materially longer observation window and build a local,
   read-only monitoring dashboard for drift, risk, failures, and data health.

Read-only current-market observation would still require a separate privacy, licensing, and
security review. Real-money order submission, broker credentials, account access, funding, leverage,
margin, derivatives, short borrowing, and self-modifying risk controls remain outside the roadmap.
