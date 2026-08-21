# Phase 2 — Real Data, Portfolio Research, and Persistent Paper Laboratory

## Objective

Extend the completed Phase 1 foundation into a reproducible research system that can ingest genuine historical market data, test strategies across multiple assets and asset classes, evaluate portfolio-level behaviour, classify market regimes, run larger bounded strategy searches, and operate a persistent paper-trading laboratory.

Phase 2 remains research and simulation only. It must remain physically incapable of placing a real-money order or moving money.

The core question remains:

> Does a systematic strategy or portfolio of strategies show a robust, repeatable, risk-adjusted edge after realistic costs when tested on data that was not used to discover or tune it?

Do not optimise for maximum headline return. Preserve the Phase 1 priorities of capital preservation, auditability, reproducibility, realistic costs, and resistance to overfitting.

---

# 1. Non-negotiable safety boundary

`TradingMode` must remain limited to:

- `BACKTEST`
- `PAPER`

There must be no `LIVE` mode.

Do not implement or add:

- live broker/exchange order submission
- broker trading credentials
- crypto exchange trading credentials
- deposits or withdrawals
- leverage or margin
- options or futures execution
- borrowed-asset short selling
- copy trading
- public trading signals
- autonomous movement of money
- autonomous modification of the Risk Engine
- an LLM directly deciding or transmitting trades

Phase 2 may introduce outbound networking only for narrowly scoped, read-only market-data providers. Network code must be isolated behind the market-data provider interface and must not expose order, account-funding, withdrawal, or execution endpoints.

Update the safety scanner and tests so they continue to reject execution surfaces while allowing explicitly approved read-only market-data transports.

No broker/exchange SDK should be required for Phase 2.

Any provider secret/API key, if a chosen read-only data source genuinely requires one, must be supplied only through environment variables or a secret store. Never commit credentials. Prefer a provider that can support the required historical research without secrets when practical.

---

# 2. Preserve and extend the Phase 1 architecture

Do not replace the working Phase 1 foundation unnecessarily.

Build on:

- immutable/versioned strategy specifications
- canonical `MarketBar`/asset models
- deterministic next-bar backtesting
- realistic fees/spread/slippage modelling
- benchmark analytics
- train/validation/test separation
- walk-forward and sensitivity testing
- independent Risk Engine
- bounded research generation
- reproducible experiment records
- local paper broker
- SQLAlchemy/Alembic persistence
- FastAPI API
- CI safety gates

Migrations must preserve existing Phase 1 data and tests.

---

# 3. Provider-backed historical market data

Create a production-quality read-only historical-data subsystem.

## Provider interface

Extend the existing provider abstraction to support at minimum:

- historical bars
- asset metadata
- supported intervals
- provider/source metadata
- corporate-action metadata where available
- deterministic pagination/retry behaviour
- data-quality diagnostics

Keep provider-specific payloads outside the rest of the application. Convert all data into canonical internal models before research or backtesting.

## Initial supported asset classes

The architecture must support:

- equities
- ETFs
- cryptocurrency
- forex
- indexes/benchmarks

Phase 2 does not need every provider to support every asset class. Provider capabilities must be explicit and testable.

## Historical-data requirements

Normalize and persist:

- timestamp
- open
- high
- low
- close
- adjusted close when applicable
- volume where meaningful
- symbol/instrument identifier
- asset class
- exchange/source
- quote currency
- interval
- timezone
- provider
- ingestion timestamp
- source dataset/version metadata

Handle and test:

- duplicate bars
- missing bars
- out-of-order bars
- invalid OHLC relationships
- non-positive prices
- timezone conversion
- daylight-saving transitions
- exchange holidays/weekends where applicable
- partial data responses
- provider retries
- rate limiting
- stale datasets

Never silently repair data in a way that changes research results. Any repair/normalisation must be deterministic, logged, and represented in dataset metadata.

---

# 4. Dataset snapshots, provenance, and reproducibility

Every research run must reference an immutable dataset snapshot.

Introduce a dataset manifest containing at minimum:

- dataset ID/version
- provider
- instruments
- asset classes
- interval
- requested start/end
- actual start/end
- row counts per instrument
- timezone normalization
- adjustment policy
- corporate-action policy
- ingestion timestamp
- raw-data checksum(s)
- canonical-data checksum(s)
- missing/invalid bar diagnostics
- provider configuration excluding secrets
- code revision where useful

Persist historical data efficiently. Parquet is preferred for larger immutable datasets, with database metadata pointing to files/artifacts. Existing JSON caching may remain for small development fixtures.

A historical backtest must be reproducible from a dataset manifest rather than silently refetching mutable remote data.

Add commands to:

- ingest/update a dataset
- validate a dataset
- list dataset snapshots
- run research against a specific immutable snapshot

---

# 5. Corporate actions and price adjustment policy

Implement a clear, documented policy for equities/ETFs.

Support at least:

- stock splits
- cash dividends where source data permits

Prevent double counting.

If adjusted prices are used, document precisely which corporate actions are already embedded in adjusted prices and how dividends are treated in the portfolio model.

Backtest results must state the adjustment policy used.

Add regression tests around split and dividend dates.

---

# 6. Multi-asset portfolio backtesting

Remove the Phase 1 single-asset limitation while remaining long-only and cash-funded.

Create a portfolio backtesting layer able to simulate multiple instruments concurrently.

Support:

- multiple open long positions
- cash balance
- position-level cost basis
- realised/unrealised P&L
- fees/spread/slippage per instrument
- portfolio equity curve
- portfolio turnover
- allocation changes
- portfolio-level drawdown
- strategy attribution
- asset attribution
- asset-class attribution
- cash exposure

No leverage, margin, or negative cash.

The portfolio engine must reject orders that would violate available cash or Risk Engine limits.

## Allocation methods

Implement a small, explainable catalogue such as:

- equal weight
- fixed configured weights
- volatility-aware weighting with strict caps
- score-weighted allocation with strict caps

Do not implement unconstrained optimiser behaviour that can create extreme allocations.

Every allocator must be deterministic and bounded.

---

# 7. Portfolio Risk Engine extensions

Extend the independent Risk Engine without allowing strategies/research code to mutate it.

Add controls for:

- maximum position weight
- maximum asset-class weight
- maximum total invested exposure
- minimum cash reserve if configured
- maximum number of simultaneous holdings
- maximum portfolio drawdown
- maximum simulated daily/weekly loss
- maximum turnover
- maximum trade frequency
- stale data rejection
- abnormal price-gap rejection
- concentration limits
- correlation-aware concentration warning/limit

Where sufficient history exists, calculate:

- rolling volatility
- rolling correlation matrix
- portfolio volatility
- marginal/risk contribution where practical

Risk controls must always dominate strategy requests.

The simulation kill switch remains mandatory.

---

# 8. Market-universe configuration

Introduce versioned research universes.

A universe definition should contain:

- universe ID/version
- asset class(es)
- instruments
- inclusion reason/category
- benchmark mapping
- quote currency
- provider/source
- date-effective metadata where applicable

Do not hard-code survivorship-biased historical index constituents as if they had always existed.

For Phase 2, it is acceptable to use explicit, owner-configured liquid instrument lists while documenting the survivorship limitation.

Support separate example research universes for equities/ETFs, crypto, and forex without implying that any instrument is recommended for investment.

---

# 9. Benchmark framework

Expand benchmark evaluation from a single asset to portfolio/universe research.

Support appropriate comparisons such as:

- buy-and-hold underlying instrument
- buy-and-hold configured benchmark ETF/index proxy
- equal-weight universe benchmark
- cash baseline where useful

Calculate:

- absolute return
- annualised return
- excess return
- tracking difference
- volatility
- Sharpe/Sortino
- maximum drawdown
- recovery time
- turnover/cost difference
- downside-risk comparison

A strategy that earns a positive return but fails to justify itself versus an appropriate passive benchmark must not automatically qualify.

---

# 10. Larger bounded strategy research

Scale the Phase 1 research engine without allowing self-modifying executable code.

The engine may generate larger batches of structured strategy configurations using approved components.

Candidate dimensions may include bounded variations of:

- moving-average windows
- momentum windows
- mean-reversion thresholds
- breakout windows
- volatility filters
- trend filters
- volume/liquidity filters when the dataset supports them
- stop/exit parameters
- position-sizing parameters
- approved indicator combinations
- regime eligibility

Requirements:

- candidate count must have a configurable hard ceiling
- all candidates must remain structured/serialisable/explainable
- random searches must use recorded seeds
- identical inputs must be reproducible
- executable source code must not be generated or rewritten by the research engine
- the research engine cannot modify Risk Engine policy
- no LLM is permitted in the decision/execution loop

Support batch execution efficiently, including safe parallelism where useful, while preserving deterministic result ordering and experiment identity.

---

# 11. Data-mining and overfitting controls

Phase 2 must become stricter as the number of experiments increases.

Implement and document controls for multiple-hypothesis/data-snooping risk.

At minimum:

- lock final hold-out periods from parameter tuning
- preserve train/validation/test chronology
- record how many candidate strategies were evaluated
- require minimum trade/sample counts
- parameter-neighbour stability checks
- walk-forward consistency
- cost-stress testing
- perturbation testing
- cross-instrument/generalisation testing where appropriate
- reject strategies dependent on one isolated period or instrument unless explicitly classified as specialised and then validated separately

Add at least one statistically defensible multiple-testing adjustment or false-discovery diagnostic appropriate to the architecture. Keep it explainable and document its limitations.

Never rank a candidate using metrics from a final hold-out set that were used to select its parameters.

---

# 12. Market-regime classification

Implement deterministic, explainable regime classification.

Initial regime dimensions may include:

- uptrend / downtrend / range
- high / normal / low volatility
- optional liquidity state where supported

Do not use future information to label the current bar.

Regime classification must be based only on information available up to the classification timestamp.

Persist regime labels with their calculation/version metadata.

Evaluate each strategy by regime:

- return
- drawdown
- Sharpe/Sortino
- trade count
- win/loss behaviour
- cost sensitivity

Allow strategies to declare approved regime eligibility, but they must still pass independent validation.

---

# 13. Cross-asset and portfolio research

Add research workflows that answer questions such as:

- Does the same strategy family generalise across instruments?
- Does combining weakly correlated strategies improve drawdown?
- Does a strategy only work in one regime?
- Does portfolio construction add value versus holding the benchmark?
- Is apparent performance explained by one instrument or one exceptional period?

Introduce portfolio-of-strategies experiments where each component strategy has already passed the appropriate validation gate.

Store full attribution so aggregate performance cannot hide a failing component.

---

# 14. Persistent paper laboratory

Create a persistent scheduled paper-simulation service.

This service may consume:

- replayed immutable historical bars for deterministic testing
- newly ingested read-only market data for forward paper observation

It must never transmit an order externally.

Requirements:

- persistent paper accounts in the database
- persistent orders/fills/audit events
- persistent portfolio snapshots
- restart-safe/idempotent processing
- checkpointing
- duplicate-cycle protection
- deterministic cycle IDs
- data freshness checks
- failure/retry logging
- kill-switch enforcement
- risk decision audit trail
- strategy attribution
- portfolio attribution

Implement a scheduler abstraction rather than tightly coupling to one operating-system scheduler.

Provide a command that performs exactly one paper cycle. Repeated scheduling can call this command/service.

Example target workflow:

```text
read-only data ingestion
        -> validate/freeze dataset increment
        -> calculate signals using only available data
        -> Risk Engine decision
        -> local simulated orders/fills
        -> mark-to-market
        -> persist portfolio/audit/metrics
        -> no external order transmission
```

---

# 15. Paper qualification lifecycle

Preserve conservative lifecycle states.

A candidate should not enter persistent paper observation merely because it had a profitable backtest.

Define explicit configurable qualification requirements, for example:

- minimum score
- minimum out-of-sample history
- minimum trades
- maximum drawdown
- acceptable cost sensitivity
- parameter stability
- walk-forward consistency
- benchmark-relative requirement
- no critical validation warnings

Do not loosen thresholds merely to ensure strategies qualify.

It is an acceptable Phase 2 result for zero strategies to qualify.

---

# 16. Performance database and experiment catalogue

Persist enough information to query the laboratory historically.

Support queries by:

- strategy family/version
- dataset version
- universe
- instrument
- regime
- run date
- lifecycle state
- score range
- benchmark outcome

Preserve immutable experiment records. Corrections should create new runs/versions rather than rewriting history.

Add database migrations and tests.

---

# 17. API and dashboard/read-model extensions

Extend the FastAPI read model with endpoints for:

## Data health

- configured providers
- dataset snapshots
- freshness
- validation warnings
- missing data

## Research

- research batches
- candidate counts
- retained/rejected counts
- multiple-testing diagnostics
- walk-forward status
- regime performance

## Portfolio

- holdings
- cash
- equity curve
- drawdown
- exposure by asset/asset class
- attribution
- benchmark comparison

## Paper laboratory

- paper accounts
- last cycle
- next expected cycle metadata if scheduled externally
- simulated orders/fills
- audit events
- kill-switch status

No endpoint may expose a live trading action.

---

# 18. CLI/scripts

Provide clear commands/scripts equivalent to:

```bash
python -m scripts.ingest_market_data --config <config>
python -m scripts.validate_dataset --dataset <dataset-id>
python -m scripts.run_research --dataset <dataset-id> --universe <universe-id>
python -m scripts.run_portfolio_backtest --dataset <dataset-id> --universe <universe-id>
python -m scripts.run_paper_cycle --account <paper-account-id>
```

Exact command names may differ if the existing CLI architecture suggests a better design.

All commands must support deterministic logging and non-zero exit codes on failure.

---

# 19. Configuration

Introduce typed configuration for:

- read-only data providers
- dataset locations
- research ceilings
- cost assumptions
- universe definitions
- benchmark mappings
- qualification thresholds
- portfolio risk limits
- scheduler/paper-cycle settings

Separate development/test configuration from owner research configuration.

Do not place secrets in repository configuration files.

---

# 20. Tests

Maintain or improve Phase 1 coverage.

Add tests for at minimum:

- read-only provider transport boundaries
- provider normalization
- provider retry/rate-limit handling
- timestamp/timezone handling
- duplicate/missing/invalid bar handling
- dataset checksums/manifests
- immutable snapshot reproducibility
- split handling
- dividend handling
- multi-asset cash accounting
- portfolio P&L
- allocation bounds
- portfolio Risk Engine controls
- correlation/concentration checks
- benchmark calculations
- research hard ceilings
- deterministic batch research
- hold-out isolation
- walk-forward testing
- parameter perturbation
- multiple-testing diagnostic
- regime classification without look-ahead
- regime-specific analytics
- persistent paper account restart/recovery
- idempotent paper cycles
- duplicate cycle rejection
- kill-switch enforcement
- stale data rejection
- no-live-execution boundary

The safety test must continue to prove that no code path can submit a real financial order.

---

# 21. CI and security

Keep all existing quality checks and extend them as required.

Required gates:

- Ruff format
- Ruff lint
- strict mypy
- pytest
- minimum coverage at least the current required threshold
- dependency consistency
- dependency vulnerability audit
- secret detection
- no-live-execution safety scan

Add tests that fail if network code appears outside approved read-only market-data modules unless explicitly allowlisted by architecture.

The safety scanner must distinguish approved market-data retrieval from forbidden execution/account-funding functionality.

---

# 22. Documentation

Update:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/RISK_MODEL.md`
- `docs/BACKTESTING_ASSUMPTIONS.md`
- `docs/ROADMAP.md`

Add documentation for:

- real-data provider architecture
- dataset provenance/versioning
- corporate-action policy
- universe/survivorship limitations
- portfolio accounting
- regime methodology
- multiple-testing/overfitting controls
- persistent paper-lab operation

Clearly state that research results and paper results do not guarantee future profitability.

---

# 23. Phase 2 example research target

Provide a small but genuine end-to-end demonstration using provider-backed historical data.

The demonstration should include multiple instruments and, where practical, more than one asset class, but should stay small enough for CI/development reproducibility.

For the demonstration:

1. ingest and freeze a historical dataset snapshot
2. validate data quality
3. run multiple reference strategy families
4. generate bounded candidate variations
5. perform chronological train/validation/test evaluation
6. run walk-forward checks
7. run cost stress tests
8. evaluate by market regime
9. compare against appropriate passive benchmarks
10. build at least one bounded long-only portfolio experiment
11. produce a ranked report
12. explain why every candidate was rejected, retained for further validation, or admitted to paper observation

Do not manipulate thresholds so that a strategy passes.

If every candidate fails, report that result as valid evidence.

---

# 24. Phase 2 completion criteria

Phase 2 is complete when all of the following are true:

- real historical data can be fetched through an approved read-only provider interface
- ingested data is normalized, validated, snapshotted, checksummed, and reproducible
- multi-asset long-only cash portfolio backtesting works
- portfolio-level risk controls work independently of strategy code
- benchmarks work at asset and portfolio/universe level
- bounded strategy research can run larger reproducible batches
- multiple-testing/overfitting diagnostics are present
- regime classification and regime-specific analytics work without look-ahead
- cross-instrument/portfolio research is supported
- persistent restart-safe paper simulation is supported
- paper cycles are idempotent and fully audited
- no live trading surface exists
- all quality/security/safety checks pass
- documentation is updated
- a genuine historical-data demonstration report is generated

---

# 25. Final report required from Codex

At completion report:

1. architecture changes
2. providers added and their read-only boundaries
3. dataset/versioning design
4. database migrations
5. portfolio engine changes
6. Risk Engine changes
7. research/validation changes
8. regime methodology
9. persistent paper-lab implementation
10. tests run and results
11. coverage
12. security/safety scan results
13. vulnerability/secret scan results
14. genuine historical demonstration results
15. benchmark comparisons
16. strategies qualified for paper observation, if any
17. known limitations
18. next recommended milestone

Fix failures before reporting completion.

Do not proceed to live-money trading in Phase 2 under any circumstances.
