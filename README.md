# Private Trading Laboratory

A private, single-user research system for testing whether systematic strategies show robust,
risk-adjusted performance after realistic costs. Version 1 is simulation-only: it has no live
execution mode, external order transmitter, broker credential fields, leverage, margin, options,
futures, short selling, or money-movement API.

Reference strategies are engineering fixtures, not investment recommendations. Synthetic results
do not predict real-market performance.

## Safety boundary

- `TradingMode` is a closed enum containing only `BACKTEST` and `PAPER`.
- Strategies request exposure; the independent Risk Engine permits or rejects it.
- The paper broker only fills locally against caller-supplied bars and writes an audit trail.
- No production dependency is an exchange/broker SDK or an outbound HTTP client.
- `scripts/check_no_live_execution.py` rejects suspicious external-execution callables, credential
  settings, network clients in runtime code, or unsafe states.
- CI and unit tests prove an unsupported mode cannot be configured.

See [AGENTS.md](AGENTS.md), [docs/PHASE1_SPEC.md](docs/PHASE1_SPEC.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and [docs/RISK_MODEL.md](docs/RISK_MODEL.md).

## Quick start

Python 3.12 or later is required.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
python -m scripts.run_backtest
```

The backtest command uses a fixed seed and time range. It prints a ranked report and writes the
machine-readable result to `reports/backtest_report.json`. Parameters are exercised on a
chronological training/development segment, nearby-parameter stability is measured on a separate
validation segment, and the displayed ranking uses the final held-out test segment.

Run the local API:

```bash
uvicorn app.api.main:app --reload
```

Useful endpoints include `/safety`, `/portfolio`, `/strategies`,
`/strategies/{strategy_id}:v{version}`, and `/research/experiments`. Interactive API documentation
is at `/docs`.

## Quality checks

```bash
ruff format --check .
ruff check .
mypy app scripts
python -m scripts.check_no_live_execution
pytest --cov=app --cov-report=term-missing
pip-audit
```

## Architecture at a glance

```text
synthetic/cached market data
          |
          v
immutable strategy spec -> desired exposure
          |                    |
          |                    v
          |             independent risk engine
          v
next-bar backtester -> analytics -> benchmark -> validation -> 0-100 risk-first score
          |
          +-> reproducible experiment records

paper mode: supplied market bar -> risk decision -> local simulated fill -> audit record
```

Persistence uses SQLAlchemy 2 and Alembic. SQLite is the local default; the schema and session
boundary are PostgreSQL-ready. Historical synthetic responses can be cached as transparent JSON.

## Reproducibility

Every experiment model records the immutable strategy version, dataset version, instruments,
period, costs, parameters, code revision, random seed, metrics, validation outcome, and rejection
reason. Strategy changes create a new version or a traceable child candidate.

## Current limitations

- One asset per backtest and long-only cash positions.
- Daily synthetic market data is the only included provider.
- Market orders drive reference backtests; limit fill mechanics are available for focused tests and
  paper simulation.
- Corporate actions are limited to explicit cash dividends on canonical bars.
- Risk-free rate and tax effects are zero/not modelled.
- The API is a local read model, not a styled dashboard.
- Paper mode consumes supplied/replayed bars; it does not connect to an exchange feed.

These are intentional Phase 1 constraints. They do not relax the prohibition on real-money
trading.
