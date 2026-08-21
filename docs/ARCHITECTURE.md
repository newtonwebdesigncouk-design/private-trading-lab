# Architecture

## Design priorities

Capital preservation, auditability, chronological correctness, reproducibility, and provider
independence take precedence over raw return or feature breadth. Domain models are Pydantic objects;
persistence models stay behind a SQLAlchemy repository boundary.

## Components

- `app/data`: canonical provider interface, deterministic multi-regime synthetic provider, JSON
  historical cache.
- `app/models`: assets, closed safety/state enums, immutable OHLCV bars, immutable/versioned
  strategy specifications.
- `app/indicators`: small functions that receive only the history available at a decision time.
- `app/strategies`: exposure-requesting interface and four reference strategies.
- `app/backtesting`: next-bar execution, cash/position accounting, costs, fills, trades, equity, and
  analytics.
- `app/benchmarks`: passive buy-and-hold comparison.
- `app/validation`: chronological splits, rolling walk-forward folds, parameter sensitivity, and
  regime labels.
- `app/scoring.py`: 0-100 weighted, risk-first score and lifecycle recommendation.
- `app/risk`: independent immutable limits and a global simulation kill-switch input.
- `app/paper_trading`: local simulated orders/fills, marked-to-market portfolio history, strategy
  attribution, and append-only audit events.
- `app/research`: bounded approved-parameter variations represented as structured specifications,
  with deterministic backtest/score/reject/retain evaluation and reproducible experiment records.
- `app/database`: SQLite/PostgreSQL-ready experiment, result, strategy, and audit persistence.
- `app/api`: local FastAPI read endpoints for portfolio, strategies, details, and research outcomes.

## Chronology boundary

At bar `t` close, a strategy receives exactly `bars[:t+1]`. A resulting order has that close as its
decision timestamp. The execution model rejects any fill whose timestamp is not later and uses the
next supplied bar's open/low/high for market/limit fill simulation. Dataset splits never shuffle.

## Dependency direction

Strategies depend on market models and indicators, never execution. Backtesting converts exposure
requests into local orders. Paper trading depends on the Risk Engine, but the Research Engine has no
reference to risk, paper, database mutation outside experiment records, or application source files.

## Persistence

Strategy rows are insert-only through the repository: a duplicate version key raises an error.
Backtest records persist their dataset identifier, period, costs, metrics, benchmark, and final
equity. Experiment rows add parameters, seed, code version, validation state, and reasons. Paper
audit rows retain every order rejection, simulated order, fill, and portfolio snapshot.

## Future adapters

A future read-only market-data adapter can implement `MarketDataProvider`. No execution-provider
contract exists in Phase 1. Any future proposal for real-money execution requires a separate threat
model, authorization, repository change, and safety review; it cannot be enabled through config.
