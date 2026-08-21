# Architecture

## Design priorities

Capital preservation, auditability, chronological correctness, reproducibility, and provider
independence take precedence over raw return or feature breadth. Domain models are immutable
Pydantic values where practical; persistence models stay behind SQLAlchemy repositories.

## Components

- `app/data/providers`: approved read-only historical-data adapters. `transport.py` is the only
  network transport and enforces HTTP GET. Yahoo Chart is the reproducible example source; Stooq is
  retained as a diagnosed adapter whose anti-bot response is rejected rather than bypassed.
- `app/data`: provider contracts, canonical normalization, calendars, corporate actions,
  content-addressed snapshots, validation, checksums, and freshness.
- `app/universe`: explicit owner-configured, versioned instrument membership and benchmark mapping.
- `app/models`: assets, the closed BACKTEST/PAPER mode enum, immutable bars, and versioned strategy
  specifications.
- `app/indicators` and `app/strategies`: history-only calculations and exposure requests.
- `app/backtesting`: preserved single-asset Phase 1 engine.
- `app/portfolio`: common-clock multi-asset accounting and equal, fixed, inverse-volatility, and
  score-weighted bounded allocation.
- `app/risk`: independent position, asset-class, portfolio, cash-reserve, turnover, concentration,
  correlation, loss, drawdown, frequency, freshness, gap, and kill-switch controls.
- `app/benchmarks`: passive per-asset, equal-weight-universe, and cash comparisons.
- `app/validation`: chronological/walk-forward splits, point-in-time regimes, perturbation,
  qualification, and false-discovery diagnostics.
- `app/research`: deterministic hard-capped candidate batches, cross-instrument validation,
  cost stress, locked holdout selection, and qualified strategy portfolios.
- `app/paper_trading`: restart-safe, idempotent local cycles with persisted accounts, orders,
  fills, snapshots, failures, and audit events.
- `app/database`: insert-oriented dataset, universe, batch, regime, experiment, and paper records.
- `app/api`: GET-only local read models for health, research, portfolios, and paper state.

## Data and chronology flow

Provider responses are normalized to UTC, sorted, de-duplicated deterministically, validated, and
frozen as JSONL. A manifest binds the exact bytes and their diagnostics with SHA-256 checksums.
Downstream services accept a dataset ID and validate all checksums before use; they do not silently
refetch changing provider data.

A daily timestamp represents when the complete bar becomes available to the laboratory. Yahoo
daily bars are conservatively normalized to the following UTC midnight. At decision bar `t`, a
strategy receives only the prefix through `t`; any generated order may fill no earlier than the next
common portfolio timestamp. Dataset splits never shuffle. Regime labels use expanding/prefix-only
history and are calculated separately at each timestamp.

## Portfolio boundary

Strategies cannot mutate cash, holdings, allocations, or risk limits. The portfolio engine aligns
assets on a common clock, turns requested exposures into target weights, proposes an order, obtains
an independent risk decision, and only then executes a local next-bar fill. Accounting records
cash, quantity, average cost, realized/unrealized P&L, dividends, fees, slippage, turnover, equity,
drawdown, exposure, attribution, and risk statistics. Long-only cash funding and a configured cash
reserve prevent leverage and negative cash.

## Research isolation

Candidate generation accepts structured parameter grids or a seeded random sample, calculates the
full candidate-space size, and refuses to exceed a hard cap. Selection sees train and validation
segments, walk-forward folds, doubled-cost stress, cross-instrument outcomes, passive benchmarks,
sample-size requirements, perturbation checks, and Benjamini-Hochberg diagnostics. The final test
segment remains locked until selection is complete. A valid batch may select no candidates.

Generated specifications cannot edit source files, risk limits, provider settings, or qualification
thresholds. A portfolio of strategies can contain only strategies whose qualification state allows
paper observation, with bounded weights.

## Persistence and idempotency

Migration `0002_phase_2_persistence` extends, rather than replaces, the Phase 1 schema. Dataset
manifests, universes, batches, and regimes are immutable catalogue records. A paper cycle ID is
derived from account, dataset, and latest instrument timestamps. Starting the same completed cycle
returns the existing record; failed cycles may be retried with a counter; order identifiers and
fills are unique. Account mutation, fills, final snapshot, and cycle completion commit atomically.

The persistent paper lab first checks the global kill switch and dataset freshness, restores any
pending simulated orders, fills them only from frozen later bars, creates new local orders, and
writes audit entries for every decision. Its scheduler contract triggers that same cycle service;
it does not create an external execution channel.

## Safety and dependency direction

Networking is contained in approved historical-provider modules. No execution-provider contract,
account/funding client, authenticated transport, or live mode exists. Strategies depend on market
models and indicators; portfolio and paper services depend on the Risk Engine; providers never
depend on strategy or execution code. The static safety scanner and tests enforce those boundaries.
