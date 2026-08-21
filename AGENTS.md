# AGENTS.md

## Project purpose

This repository is a single-user, private-use algorithmic trading research laboratory. The owner does not intend to sell it or provide trading services to customers.

## Permanent safety boundary

The project must remain physically incapable of transmitting a real-money financial order.

For Phase 4, `TradingMode` remains limited to `BACKTEST` and `PAPER`. Replay/genuine-forward labels are provenance labels only and must not become execution modes.

Do not implement, enable, stub with real endpoints, or request trading credentials for:

- live brokerage or crypto order submission
- deposits, withdrawals, transfers, or account funding
- leverage or margin
- options or futures execution
- borrowed-asset short selling
- automated movement of money
- autonomous modification of the Risk Engine
- customer/copy-trading features
- an LLM directly deciding or transmitting trades

Paper trading, replay, simulation, genuine forward observation, and bounded automated research are permitted.

Outbound networking is permitted only inside explicitly approved read-only market-data providers. Market-data network code must remain isolated behind provider interfaces and must not expose order placement, funding, withdrawal, transfer, or execution functionality.

No broker/exchange trading SDK should be required in Phase 4.

If a read-only data provider requires a credential, it must come only from environment variables or a secret store and must grant no trading/funding permissions. Prefer credential-free sources where practical. Never commit credentials.

Maintain tests and static safety checks that fail if a `LIVE` mode, external order transmitter, trading credential surface, money-movement API, unsafe HTTP method, trading SDK, or other execution path becomes possible.

## Engineering priorities

1. Capital preservation and auditability before return maximisation.
2. Honest forward evidence before optimisation.
3. Robustness and benchmark-relative evidence before headline return.
4. Deterministic, reproducible backtests, generations, replays, and PAPER cycles.
5. No look-ahead bias, future-data leakage, or forward-period contamination.
6. Immutable dataset snapshots, research generations, strategy versions, trial manifests, and provenance.
7. Realistic fees, spreads, slippage, turnover, and conservative execution assumptions.
8. Strong anti-overfitting and multiple-testing controls for large research batches.
9. Frozen active-trial configuration and lifecycle thresholds.
10. Independent Risk Engine with immutable/versioned risk policies and final authority.
11. Restart-safe, idempotent orchestration and duplicate prevention.
12. Bounded owner-controlled strategy grammar; no arbitrary executable-code generation.
13. Strong typing, tests, linting, secret scanning, dependency auditing, and CI.
14. Explainable deterministic methods before heavyweight ML.
15. Treat zero retained/qualified strategies as a valid research outcome.
16. Never claim replay/backtest performance is genuine forward performance.

## Recommended stack

Continue the established Python 3.12+ stack: FastAPI, SQLAlchemy, Alembic, Pydantic, NumPy, Polars/Pandas as appropriate, SciPy, scikit-learn only where justified, pytest, Ruff and mypy. Keep SQLite useful for local development and the persistence layer PostgreSQL-ready.

Keep immutable historical/current market evidence content-addressed/checksummed using the established snapshot/provenance model.

## Working method

- Work only on the requested dedicated branch.
- Read `docs/PHASE4_SPEC.md` before implementing Phase 4.
- Preserve completed Phase 1–3 behaviour unless Phase 4 deliberately extends it.
- Extend working architecture rather than unnecessarily replacing it.
- Keep commits small and descriptive.
- Run tests, linting, type checking, safety scanning, dependency auditing, and secret detection before reporting completion.
- Fix failures rather than merely listing them.
- Do not commit secrets.
- Keep every result reproducible from code revision, research-generation ID, strategy version, trial ID, dataset/version, universe version, risk policy, allocation policy, costs, benchmark, cutoff timestamp, and random seed where relevant.
- Never silently alter historical or forward evidence.
- Never tune an active forward trial using observations produced after its start.
- Never lower qualification/research thresholds after inspecting results to force a pass.
- Never silently expand the candidate search space after seeing outcomes.
- Any material strategy, benchmark, allocation, cost, risk, research, or qualification-policy change creates a new immutable version/generation/trial.
- Genuine forward observations, locked historical hold-out results, historical research, and replay records must remain clearly separated in persistence and reporting.
- Automated candidate generation must remain configuration-only within the approved grammar and must never write/execute arbitrary strategy source code.
- Drift from an active trial may create a request for a future research generation, but must not mutate the active strategy.

## Completed baseline

Phase 1 established deterministic strategy research, cost-aware backtesting, risk-first scoring, chronological validation, bounded strategy generation, an independent Risk Engine, local PAPER execution, experiment tracking, persistence, API endpoints, CI, and the hard no-live-execution boundary.

Phase 2 added genuine GET-only historical-data ingestion, immutable dataset provenance, corporate-action policy, multi-asset portfolio research, broader bounded research, multiple-testing diagnostics, deterministic regime analysis, portfolio risk controls, and restart-safe persistent PAPER simulation.

Phase 3 added immutable forward trials, current read-only incremental data evidence, genuine subsequent-data observation, restart-safe idempotent forward PAPER cycles, multiple-strategy PAPER portfolios, lifecycle qualification/pause/fail rules, degradation/drift diagnostics, champion/challenger comparison, regime-aware observation, operational health/read models, and clearly separated replay verification.

Treat the merged Phase 1–3 implementation on `main` as the known-good baseline.

## Phase 4 completion definition

Phase 4 must add immutable bounded research generations, approved configuration-only strategy grammar, candidate lineage/mutation, stronger anti-overfitting controls, research cutoffs, deterministic challenger admission into new Phase 3-compatible forward trials, champion/challenger governance, optional regime-aware PAPER allocation, ensemble/diversification research, research budgets, restart-safe research orchestration, read models, reporting, migrations, and tests.

All Phase 4 functionality must remain incapable of placing or transmitting a real-money trade.
