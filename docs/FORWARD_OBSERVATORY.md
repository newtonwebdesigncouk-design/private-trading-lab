# Forward PAPER Observatory

## Purpose and boundary

Phase 3 observes frozen strategies after a declared start without turning their outcomes into a new
parameter-tuning set. It is a private PAPER laboratory. `TradingMode` remains exactly `BACKTEST` and
`PAPER`; `GENUINE_FORWARD` and `REPLAY` are evidence provenance, not execution modes.

There is no broker/exchange client, authenticated trading credential, financial account, funding or
money-movement model, external order transport, margin, leverage, derivative, borrowed short, copy
trading, or customer trading surface. All orders and fills are immutable local simulation records.

## Frozen trials and contamination control

`ForwardTrialManifest` freezes and fingerprints:

- trial/portfolio identity, strategy source hash, version and parameters;
- assets/universe, benchmark, starting PAPER capital and allocation;
- commission/spread/slippage assumptions and the independent Risk Engine policy;
- provider, interval, adjustment, corporate-action, staleness and warm-up data policy;
- qualification, degradation and baseline thresholds;
- UTC start, random seed, code revision and evidence provenance.

The repository refuses a duplicate trial row and verifies the content fingerprint whenever it loads
one. It also binds the persisted portfolio to the complete set of trial fingerprints. A material
change therefore requires a new strategy version, trial, and (when its sleeve set changes) portfolio
identity. Forward tables are not imported by research selection. Bars before the start can warm an
indicator but the repository rejects them as forward observations.

## Evidence and current provider behavior

`IncrementalMarketDataCollector` uses the Phase 2 `MarketDataProvider` contract. Production current
updates use the public Yahoo Chart adapter; its sole network transport constructs literal HTTP GET
requests. The provider declares `read_only=true` and `requires_secret=false`. A trial binds the exact
provider/version and daily interval at creation.

Each accepted update creates an immutable evidence directory containing canonical JSONL, per-file
checksums, response audit checksum/warnings, requested/fetched times, and a manifest linked to its
predecessor. Repeated data adds nothing. Duplicate/out-of-order/future data, invalid or partial
responses, configured gaps, provider-policy mismatch, and excessive staleness fail closed. The
blocked cycle records zero orders/fills and pauses trials with an explainable event. A later valid
update resolves the event in the same transaction as its completed cycle.

The current provider is disabled by default. No checked-in command auto-creates a genuine trial or
runs continuously. Owner commands are scheduler-neutral:

```bash
python -m scripts.create_forward_trials --config config/my_phase3_forward.json
python -m scripts.run_forward_cycle --portfolio my-forward-portfolio
```

The creation command refuses a backdated genuine start. A cycle acquires an expiry lease, loads all
trials, appends safe evidence, and releases the lease on every exit. If multiple bars are backfilled,
all may become honest unseen observations but only the newest safe bar advances PAPER execution.

## Cycle, accounting, and risk

A cycle ID hashes portfolio, evidence manifest, market timestamp and provenance. Completed/blocked
cycles return `DUPLICATE` on repeat. Failed/in-progress cycles increment a retry counter and restart
from the last committed portfolio. Observations, signals, local next-bar orders/fills, portfolio and
trial snapshots, benchmarks, degradation, lifecycle transitions and audit completion commit
atomically.

Concurrent trials own fixed cash sleeves; unallocated capital remains reserve. Recent performance
cannot silently reallocate it. Strategies request only exposure in `[0,1]`. The independent frozen
Risk Engine remains authoritative for strategy/instrument/class/gross/correlated exposure, cash,
turnover/frequency, daily/weekly loss, drawdown, freshness, abnormal moves and the global kill
switch. Accounting is fractional, long-only and cash-funded with no negative cash.

## Lifecycle, drift, and comparison

States are `READY_FOR_FORWARD`, `OBSERVING`, `PAUSED_DATA_QUALITY`, `PAUSED_RISK`,
`FAILED_FORWARD`, `QUALIFIED_FORWARD`, and `RETIRED`. Every evaluation records a stable rule ID,
reasons, metrics and frozen policy versions. Minimum elapsed time, observations, completed trades,
drawdown, Sharpe, benchmark-relative return, cost resilience, data quality and risk evidence must
all pass. Insufficient evidence stays `OBSERVING`. Repeated failure reaches deterministic retirement.

`QUALIFIED_FORWARD` means only that the frozen PAPER observation rules passed. It grants no new
capability and does not imply suitability or profitable future performance. Zero qualified trials
is a complete, valid result.

Rolling deterministic diagnostics cover return, volatility, Sharpe/Sortino, drawdown,
benchmark-relative return, hit rate/expectancy, turnover/cost ratio, signal frequency, regime mix,
and data age. Frozen warning/pause/fail thresholds drive lifecycle decisions. Regime labels reuse
the Phase 2 prefix-only classifier. Champion/challenger output ranks states/performance and reports
pairwise return correlation, overlapping exposure, drawdown contribution, strategy attribution,
strategy benchmarks and a frozen-weight portfolio benchmark.

## Operations and API

Bearer-protected GET-only endpoints are `/forward/trials`, `/forward/trials/{trial_id}`,
`/forward/portfolio`, `/forward/performance`, `/forward/health`, `/forward/cycles`, and
`/forward/data-quality`. Health includes latest cycle/success, lease owner/expiry, provider identity,
data age, missing assets, trial states/provenance, data-quality status, database connectivity, recent
failures and kill switch. The checked-in API demonstrates the immutable replay report; owner
deployments may construct `ForwardReadModel` over their Phase 3 database.

Run `python -m scripts.run_phase3_replay` to reveal the frozen Phase 2 snapshot one timestamp at a
time in a temporary, separate replay store. The report and every record say `REPLAY`. See
[PHASE3_REPLAY_RESULTS.md](PHASE3_REPLAY_RESULTS.md).
