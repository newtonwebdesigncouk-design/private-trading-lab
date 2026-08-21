# AGENTS.md

## Project purpose

This repository is a single-user, private-use algorithmic trading research laboratory. The owner does not intend to sell it or provide trading services to customers.

## Non-negotiable Phase 1 safety rule

Phase 1 must be physically incapable of transmitting a real-money financial order.

Do not implement, enable, stub with real endpoints, or request credentials for:

- live brokerage order submission
- live crypto order submission
- deposits or withdrawals
- leverage or margin
- options or futures execution
- borrowed-asset short selling
- automated movement of money
- autonomous modification of the risk engine

Paper trading and simulation are permitted. Read-only market-data integrations are permitted.

Add tests that fail if a `LIVE` execution mode or live-order transport is introduced during Phase 1.

## Engineering priorities

1. Capital preservation and auditability before return maximisation.
2. Deterministic, reproducible backtests.
3. No look-ahead bias or future-data leakage.
4. Realistic modelling of fees, spread and slippage.
5. Train/validation/test separation and walk-forward testing.
6. Immutable, versioned strategy specifications.
7. Risk engine independent from strategy/research code.
8. Strong typing, tests, linting, secret scanning and CI.
9. Broker/data-provider abstractions rather than tight coupling.
10. Simple, explainable methods before heavyweight ML.

## Recommended stack

Prefer Python 3.12+, FastAPI, SQLAlchemy, Alembic, Pydantic, NumPy, Polars/Pandas as appropriate, SciPy, scikit-learn only where justified, pytest, Ruff and mypy. Use SQLite for local development if helpful and keep persistence PostgreSQL-ready.

## Working method

- Work on a dedicated branch.
- Keep commits small and descriptive.
- Run tests, linting and type checking before reporting completion.
- Fix failures rather than merely listing them.
- Do not commit secrets.
- Keep every research result reproducible from code version, strategy version, dataset/version, parameters and random seed where relevant.

## Phase 1 completion definition

A user must be able to run a reproducible backtest over reference strategies, receive cost-aware performance metrics and rankings, and run simulated/paper execution without any possible code path to a live-money trade.
