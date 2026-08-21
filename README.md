# Private Trading Lab

A private-use algorithmic trading research laboratory for strategy discovery, backtesting, validation, ranking, and paper trading.

## Phase 1 safety boundary

This repository must not contain any code path capable of transmitting a live financial order. Phase 1 is limited to historical data, read-only market data, deterministic backtesting, simulated execution, paper trading, research, validation, and risk controls.

No broker trading credentials, live order endpoints, deposits, withdrawals, leverage, margin, options, futures, short selling, or autonomous movement of money are permitted in Phase 1.

## Goal

Build a reproducible research system that asks whether systematic strategies can outperform appropriate passive benchmarks after realistic fees, spreads, slippage and tax-aware reporting while controlling drawdown and avoiding overfitting.

## Development branch

Initial development is being prepared on `codex/phase-1-foundation`.

See `AGENTS.md` for mandatory development constraints and `docs/PHASE1_SPEC.md` for the first implementation milestone.
