# AGENTS.md

## Project purpose

This repository is a single-user, private-use algorithmic trading research laboratory. The owner does not intend to sell it or provide trading services to customers.

## Permanent safety boundary

The project must remain physically incapable of transmitting a real-money financial order unless a separate future milestone explicitly changes that boundary after independent review.

For Phase 2, `TradingMode` must remain limited to `BACKTEST` and `PAPER`.

Do not implement, enable, stub with real endpoints, or request trading credentials for:

- live brokerage order submission
- live crypto order submission
- deposits or withdrawals
- leverage or margin
- options or futures execution
- borrowed-asset short selling
- automated movement of money
- autonomous modification of the Risk Engine

Paper trading and simulation are permitted.

Phase 2 may add outbound networking only for explicitly approved read-only market-data providers. Market-data network code must be isolated behind the provider interface and must not expose order placement, account funding, withdrawal, or execution functionality.

No broker/exchange trading SDK should be required in Phase 2.

If a read-only data provider requires a credential, it must come only from environment variables or a secret store. Never commit credentials.

Add and maintain tests that fail if a `LIVE` mode, external order transmitter, broker credential surface, money-movement API, or other execution path becomes possible.

## Engineering priorities

1. Capital preservation and auditability before return maximisation.
2. Deterministic, reproducible backtests and paper cycles.
3. No look-ahead bias or future-data leakage.
4. Realistic modelling of fees, spread and slippage.
5. Immutable dataset snapshots and provenance.
6. Train/validation/test separation, walk-forward testing, and strict hold-out isolation.
7. Immutable, versioned strategy specifications.
8. Risk Engine independent from strategy/research code.
9. Strong typing, tests, linting, secret scanning, dependency auditing, and CI.
10. Provider abstractions rather than tight coupling.
11. Explainable, bounded methods before heavyweight ML.
12. Treat zero qualifying strategies as a valid research outcome.

## Recommended stack

Continue the established Python 3.12+ stack: FastAPI, SQLAlchemy, Alembic, Pydantic, NumPy, Polars/Pandas as appropriate, SciPy, scikit-learn only where justified, pytest, Ruff and mypy. Keep SQLite useful for local development and the persistence layer PostgreSQL-ready.

For larger immutable historical datasets, prefer a reproducible columnar snapshot format such as Parquet with database metadata/manifests.

## Working method

- Work only on the requested dedicated branch.
- Read `docs/PHASE2_SPEC.md` before implementing Phase 2.
- Preserve the completed Phase 1 behaviour unless a Phase 2 change deliberately extends it.
- Keep commits small and descriptive.
- Run tests, linting, type checking, safety scanning, dependency auditing, and secret detection before reporting completion.
- Fix failures rather than merely listing them.
- Do not commit secrets.
- Keep every research result reproducible from code revision, strategy version, dataset/version, universe version, parameters, costs, and random seed where relevant.
- Never silently alter historical source data; deterministic normalisation/repair must be logged and represented in dataset metadata.
- Never tune against the final hold-out set.
- Never loosen qualification thresholds merely to produce a qualifying strategy.

## Phase 1 baseline

Phase 1 established deterministic synthetic/cached data, reference strategies, cost-aware backtesting, risk-first scoring, chronological validation, bounded strategy generation, an independent Risk Engine, local paper execution, experiment tracking, persistence, API endpoints, CI, and a hard no-live-execution safety boundary.

Treat Phase 1 as the known-good baseline.

## Phase 2 completion definition

Phase 2 must add genuine read-only historical-data ingestion with immutable provenance, multi-asset long-only cash portfolio backtesting, portfolio-level risk controls, broader bounded strategy research, stronger overfitting/multiple-testing controls, deterministic regime analysis, cross-instrument/portfolio research, and persistent restart-safe paper simulation.

All of this must remain incapable of placing a real-money trade.
