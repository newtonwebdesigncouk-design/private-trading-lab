# Phase 1 — Trading Laboratory Foundation

## Objective

Build a reproducible, single-user algorithmic trading research platform that can discover, backtest, validate, rank and paper-trade strategies while remaining physically incapable of placing a real-money trade.

## Required stack

Prefer Python 3.12+, FastAPI, Pydantic, SQLAlchemy/Alembic, SQLite for local development with PostgreSQL-ready models, NumPy, Polars/Pandas as appropriate, SciPy, scikit-learn only when justified, pytest, Ruff, mypy, Docker and GitHub Actions.

## 1. Market data

Create canonical OHLCV models supporting equities, ETFs, crypto, forex and benchmarks. Include timestamp, OHLC, adjusted close where applicable, volume, asset, asset class, quote currency, source/exchange and interval. Build a provider interface and a deterministic synthetic-data provider for tests. Cache historical data locally. Prevent look-ahead bias.

## 2. Strategy model

Create immutable/versioned strategy specifications containing ID, version, name, description, asset class, instruments, timeframe, indicators, entry/exit conditions, stops, sizing method, parameters, creation method, parent strategy and creation timestamp.

Implement reference strategies only to validate the engine: moving-average crossover, momentum, mean reversion and breakout.

## 3. Backtester

Implement deterministic portfolio accounting with starting capital, cash, positions, simulated market/limit orders, timestamps, commissions, fees, spread, slippage, dividends where applicable, realised/unrealised P&L and equity curve. Never assume frictionless execution. Prevent same-bar impossible fills and future-data leakage.

## 4. Performance analytics

Calculate total/annualised return, volatility, Sharpe, Sortino, maximum drawdown, recovery time, win/loss rate, average win/loss, profit factor, expectancy, trade count, turnover, exposure, fees and slippage cost. Compare against suitable passive benchmarks.

## 5. Validation

Implement train/validation/test separation, out-of-sample evaluation, walk-forward testing, parameter-sensitivity tests and architecture for market-regime testing. Flag fragile strategies that only work at one narrow parameter combination.

## 6. Strategy scoring

Score 0–100 using risk-adjusted and robustness factors rather than return alone. States: CREATED, BACKTESTING, REJECTED, VALIDATION, PAPER_ELIGIBLE, PAPER_TRADING, QUALIFIED, RETIRED. There must be no LIVE state.

## 7. Independent risk engine

Risk code must be independent from strategy/research code. Implement configurable maximum position size, asset-class exposure, portfolio exposure, simulated daily/weekly loss, drawdown, concurrent positions, trade frequency, stale-data rejection and abnormal-price rejection. Include `TRADING_KILL_SWITCH` for simulation/paper trading. Strategy generation must not be able to modify these controls.

## 8. Paper trading

Create broker-neutral simulated execution using live read-only or replayed market data. Maintain simulated cash, positions, orders, fills, fees, P&L, portfolio history and strategy attribution. Persist a complete audit trail. Never transmit an external order.

## 9. Research engine

Create bounded deterministic strategy generation capable of varying approved parameters and indicators, creating candidate strategy specifications, backtesting them, rejecting weak candidates and retaining promising ones. Do not use an LLM to make financial decisions and do not allow self-modifying execution/risk code.

## 10. Experiment tracking

Record strategy version, dataset/version, instruments, time period, cost assumptions, parameters, code version/commit, random seed, metrics, validation status and rejection reason for every experiment.

## 11. API/dashboard foundation

Provide backend endpoints (and only minimal UI if useful) for simulated portfolio state, strategy counts/status, strategy detail, equity curve/trades/metrics/benchmark/drawdown/validation/costs/parameters, and recent research experiments.

## 12. CI and tests

Add formatting, linting, type checking, unit tests, integration tests, backtest regression tests, accounting tests, fee/slippage tests, risk-engine tests, anti-look-ahead tests, deterministic strategy tests, dependency/security checks and secret detection.

Add a critical automated test proving there is no code path/configuration capable of live order submission.

## Forbidden in Phase 1

Do not implement live order submission, broker trading credentials, deposits/withdrawals, leverage, margin, options, futures, borrowed-asset shorting, copy trading, customer accounts, subscriptions, public signals or autonomous movement of money.

## First milestone

The repository should support commands equivalent to:

```bash
pytest
python -m scripts.run_backtest
```

The sample backtest must produce reproducible, cost-aware results for multiple reference strategies and rank them with explicit pass/fail/further-validation reasons.

Before reporting completion, run linting, type checking and tests and fix failures.

At completion report architecture, files added, tests run/results, sample backtest results, known limitations, security findings and the next recommended milestone.
