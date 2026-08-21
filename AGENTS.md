# AGENTS.md

## Project purpose

This repository is a single-user, private-use algorithmic trading research laboratory. The owner does not intend to sell it or provide trading services to customers.

## Permanent safety boundary

The project must remain physically incapable of transmitting a real-money financial order unless a separate future milestone explicitly changes that boundary after independent review.

For Phase 3, `TradingMode` must remain limited to `BACKTEST` and `PAPER`. A replay/testing label may exist for observation provenance, but it must not create a new execution mode.

Do not implement, enable, stub with real endpoints, or request trading credentials for:

- live brokerage order submission
- live crypto order submission
- deposits or withdrawals
- leverage or margin
- options or futures execution
- borrowed-asset short selling
- automated movement of money
- autonomous modification of the Risk Engine

Paper trading, replay, simulation, and genuine forward observation are permitted.

Outbound networking is permitted only inside explicitly approved read-only market-data providers. Market-data network code must remain isolated behind provider interfaces and must not expose order placement, account funding, withdrawal, transfer, or execution functionality.

No broker/exchange trading SDK should be required in Phase 3.

If a read-only data provider requires a credential, it must come only from environment variables or a secret store and must grant no trading/funding permissions. Prefer credential-free sources where practical. Never commit credentials.

Maintain tests and static safety checks that fail if a `LIVE` mode, external order transmitter, broker trading credential surface, money-movement API, unsafe HTTP method, trading SDK, or other execution path becomes possible.

## Engineering priorities

1. Capital preservation and auditability before return maximisation.
2. Honest forward evidence before optimisation.
3. Deterministic, reproducible backtests, replays, and paper cycles.
4. No look-ahead bias, future-data leakage, or forward-period contamination.
5. Immutable dataset snapshots, trial manifests, and provenance.
6. Realistic fees, spreads, slippage, and conservative execution assumptions.
7. Frozen forward-trial configuration and lifecycle thresholds.
8. Independent Risk Engine with immutable/versioned risk policies.
9. Restart-safe, idempotent orchestration and duplicate prevention.
10. Strong typing, tests, linting, secret scanning, dependency auditing, and CI.
11. Provider abstractions rather than tight coupling.
12. Explainable deterministic methods before heavyweight ML.
13. Treat zero qualifying strategies as a valid and useful outcome.
14. Never claim replay/backtest performance is genuine forward performance.

## Recommended stack

Continue the established Python 3.12+ stack: FastAPI, SQLAlchemy, Alembic, Pydantic, NumPy, Polars/Pandas as appropriate, SciPy, scikit-learn only where justified, pytest, Ruff and mypy. Keep SQLite useful for local development and the persistence layer PostgreSQL-ready.

Keep immutable historical/current market evidence content-addressed/checksummed using the established snapshot/provenance model.

## Working method

- Work only on the requested dedicated branch.
- Read `docs/PHASE3_SPEC.md` before implementing Phase 3.
- Preserve completed Phase 1 and Phase 2 behaviour unless Phase 3 deliberately extends it.
- Keep commits small and descriptive.
- Run tests, linting, type checking, safety scanning, dependency auditing, and secret detection before reporting completion.
- Fix failures rather than merely listing them.
- Do not commit secrets.
- Keep every result reproducible from code revision, strategy version, trial ID, dataset/version, universe version, risk policy, parameters, costs, benchmark, and random seed where relevant.
- Never silently alter historical or forward evidence.
- Never tune an active forward trial using observations produced after its start.
- Never lower qualification thresholds retroactively to force a strategy to pass.
- Any material strategy, benchmark, allocation, cost, risk, or qualification-policy change creates a new version/trial.
- Genuine forward observations and historical replay records must remain clearly separated in persistence and reporting.

## Completed baseline

Phase 1 established deterministic strategy research, cost-aware backtesting, risk-first scoring, chronological validation, bounded strategy generation, an independent Risk Engine, local paper execution, experiment tracking, persistence, API endpoints, CI, and a hard no-live-execution boundary.

Phase 2 added genuine GET-only historical-data ingestion, immutable dataset provenance, corporate-action policy, multi-asset portfolio research, broader bounded research, multiple-testing diagnostics, deterministic regime analysis, portfolio risk controls, and restart-safe persistent paper simulation.

Treat the merged Phase 1 and Phase 2 implementation on `main` as the known-good baseline.

## Phase 3 completion definition

Phase 3 must add frozen forward trials, current read-only incremental data collection, genuine subsequent-data observation, restart-safe idempotent forward paper cycles, multiple-strategy paper portfolios, lifecycle qualification/pause/fail rules, degradation/drift diagnostics, champion/challenger comparison, regime-aware observation, operational health/read models, and a clearly separated replay harness for engineering verification.

All Phase 3 functionality must remain incapable of placing or transmitting a real-money trade.
