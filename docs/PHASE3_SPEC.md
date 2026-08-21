# Phase 3 — Forward Paper Observatory and Strategy Governance

## Objective

Extend the completed Phase 2 research platform into a long-running, restart-safe **forward paper observation system** using current read-only market data.

Phase 3 is not a live-trading milestone. It exists to collect honest forward evidence that was unavailable when strategies were researched or backtested.

The core question is:

> After a strategy is frozen, does it continue to show useful risk-adjusted behaviour on genuinely subsequent market data, relative to its frozen benchmark and risk budget, without retuning against the observation period?

A Phase 3 completion is successful even if every strategy fails, is paused, or remains unqualified because insufficient forward evidence exists.

---

## 1. Permanent safety boundary

`TradingMode` must remain limited to `BACKTEST` and `PAPER`. There must be no `LIVE` mode.

Do not implement or expose:

- live broker/exchange order submission
- broker or exchange trading credentials
- account funding, deposits, withdrawals, transfers, or money movement
- leverage or margin
- options or futures execution
- borrowed-asset short selling
- copy trading or customer accounts
- autonomous modification of the Risk Engine
- an LLM directly deciding or transmitting trades

Networking is allowed only inside explicitly approved **read-only market-data providers**. Preserve and strengthen `scripts/check_no_live_execution.py` so account/order/funding surfaces, unsafe HTTP methods, trading SDKs, and execution transports remain forbidden.

Phase 3 must be physically incapable of transmitting a real-money financial order.

---

## 2. Forward-only observation model

Create a first-class `ForwardTrial`/equivalent model.

A trial must freeze at creation:

- trial ID
- strategy ID/version
- strategy source code/config fingerprint
- universe version
- benchmark definition
- starting simulated capital
- cost/slippage assumptions
- risk configuration/version
- provider/data policy
- start timestamp
- minimum observation requirements
- qualification thresholds
- code revision

Once a trial starts, these values are immutable. Any material strategy/parameter/risk/benchmark change creates a new trial rather than rewriting history.

The trial must never ingest bars earlier than its declared forward start as forward evidence. Historical replay may be used only in explicit test/demo mode and must be labelled as replay, never as genuine forward observation.

---

## 3. Current read-only market-data ingestion

Extend the Phase 2 provider architecture to support safe incremental updates from approved credential-free/read-only sources where practical.

Requirements:

- GET-only retrieval
- no account endpoints
- no order endpoints
- no broker/exchange SDK dependency
- deterministic canonicalisation
- market timezone/calendar awareness
- stale/future/duplicate bar rejection
- gap diagnostics
- immutable append-only snapshot/version manifests
- checksums and provenance
- provider response metadata sufficient for audit without storing secrets
- explicit handling of adjusted/unadjusted data and corporate actions

Incremental ingestion must be idempotent. A repeated cycle with the same source data must not create duplicate evidence or duplicate paper trades.

Provider failure must fail closed: no new simulated trade decision may use stale or incomplete data beyond configured freshness limits.

---

## 4. Scheduled forward cycles

Create a durable orchestration layer and CLI capable of running one safe forward cycle at a time.

A cycle should perform, in order:

1. acquire an idempotency/lease lock
2. load active forward trials
3. retrieve/validate permitted new read-only market data
4. persist immutable data evidence
5. verify freshness and chronology
6. compute strategy signals using only information available at that point
7. submit desired simulated exposure to the independent Risk Engine
8. create/fill only local paper orders according to existing execution assumptions
9. mark positions to market
10. persist portfolio/trial metrics and benchmark state
11. evaluate pause/retirement/qualification diagnostics
12. write a complete audit record
13. release the lock atomically

Support safe restart after interruption. A partially completed cycle must not duplicate orders, fills, data, or P&L when retried.

Provide a scheduler-neutral command such as:

```bash
python -m scripts.run_forward_cycle
```

The command must be suitable for cron, a managed scheduler, or manual execution without embedding a fragile always-on scheduler into core trading logic.

---

## 5. Strategy freeze and contamination prevention

Forward observation must not become another tuning dataset.

Implement controls so:

- active trial parameters cannot be edited
- candidate generation cannot mutate an active trial
- forward observations are tagged separately from research/backtest data
- research code cannot silently include forward-trial results in parameter selection
- a strategy changed after seeing forward results receives a new strategy version and new forward trial
- qualification thresholds cannot be lowered retroactively for an active trial

Store a hash/fingerprint proving the trial configuration remained unchanged.

---

## 6. Qualification, pause, and retirement policy

Create explainable rule-based lifecycle evaluation.

Suggested states:

- `READY_FOR_FORWARD`
- `OBSERVING`
- `PAUSED_DATA_QUALITY`
- `PAUSED_RISK`
- `FAILED_FORWARD`
- `QUALIFIED_FORWARD`
- `RETIRED`

Do not add a state implying live-money approval.

Qualification must require configurable minimum evidence, such as:

- minimum elapsed observation period
- minimum independent trading opportunities/trades where applicable
- acceptable maximum drawdown
- acceptable risk-adjusted performance
- benchmark-relative evidence
- cost resilience
- no unresolved data-quality failures
- no risk-limit breaches
- sufficient sample size

Do not hard-code a promise that any strategy will qualify. Insufficient evidence must produce `OBSERVING`, not a forced pass.

`QUALIFIED_FORWARD` means only that the strategy met the Phase 3 paper-observation rules. It must not enable or imply live execution.

---

## 7. Drift and degradation detection

Add rolling diagnostics for active trials, including where statistically meaningful:

- rolling return
- rolling volatility
- rolling Sharpe/Sortino
- rolling drawdown
- benchmark-relative return
- hit rate/expectancy drift
- turnover/cost drift
- signal frequency drift
- regime mix
- data freshness/quality

Implement explainable degradation rules capable of pausing or failing a paper trial when predefined limits are breached.

Avoid complex ML drift systems unless a simple deterministic approach is demonstrably insufficient.

---

## 8. Champion/challenger observation

Support multiple frozen strategies/trials running concurrently against the same immutable market observations.

Create comparison reports for:

- strategy vs benchmark
- strategy vs strategy
- portfolio of strategies vs benchmark
- contribution and attribution
- correlation/concentration
- overlapping exposure
- drawdown contribution

Any simulated capital allocation between strategies must go through portfolio risk budgeting and must never permit negative cash, margin, or leverage.

Do not allow a strategy to gain simulated capital merely because it has recently performed well unless the allocation rule was defined before the relevant evaluation window or is being tested as a new versioned policy.

---

## 9. Regime-aware observation

Reuse the Phase 2 no-lookahead regime classifier.

Track performance by regime during forward observation. If implementing regime-dependent routing/allocation:

- the rule must be frozen before the observed bar
- no hindsight regime labels may be used for decisions
- the routing rule must be versioned and auditable
- changing the rule creates a new policy/trial version

Regime selection must remain deterministic and explainable.

---

## 10. Forward paper portfolio and risk budgeting

Extend portfolio simulation for multiple active trials/strategies.

Implement configurable simulated risk budgets, including:

- maximum strategy allocation
- maximum instrument exposure
- maximum asset-class exposure
- maximum correlated exposure/concentration
- maximum portfolio drawdown
- daily/weekly loss guardrails
- maximum turnover/trade frequency
- stale-data lockout
- global kill switch

The Risk Engine remains authoritative and independent. Strategy/research code cannot alter these limits at runtime.

---

## 11. Persistence and auditability

Add database migrations/models as needed for:

- forward trials
- trial manifests/fingerprints
- forward cycles
- cycle leases/idempotency keys
- observations
- simulated signals/orders/fills
- benchmark snapshots
- portfolio snapshots
- lifecycle decisions
- data-quality events
- degradation events
- audit events

Every lifecycle transition must record the rule/evidence that caused it.

PostgreSQL compatibility must remain first-class while SQLite remains usable for local development/testing.

---

## 12. API and dashboard read models

Add bearer-protected GET-only read models for Phase 3, such as:

- `/forward/trials`
- `/forward/trials/{trial_id}`
- `/forward/portfolio`
- `/forward/performance`
- `/forward/health`
- `/forward/cycles`
- `/forward/data-quality`

Expose enough information for a private dashboard to display:

- observing/paused/failed/qualified trial counts
- simulated equity and cash
- current simulated positions
- benchmark comparison
- drawdown
- forward-only performance
- strategy attribution
- latest successful cycle
- latest market-data timestamp/age
- provider/data-quality status
- risk/kill-switch state
- qualification progress and missing evidence

Do not create any API endpoint capable of placing or transmitting an order.

---

## 13. Replay/demo mode

Because genuine forward evidence takes real elapsed time, provide a deterministic replay harness for engineering verification.

Replay mode must:

- be clearly marked `REPLAY`, never genuine forward evidence
- consume an immutable historical snapshot chronologically one cycle at a time
- exercise restart/idempotency/failure recovery
- exercise lifecycle and drift rules
- produce a report without contaminating genuine forward-trial records

Create a Phase 3 demonstration report showing the mechanics work, while explicitly stating that replay results are not forward performance claims.

---

## 14. Observability and operational health

Add structured operational diagnostics for:

- last cycle start/end/status
- lock ownership/expiry
- provider health
- data age
- missing/gapped assets
- trial count/state
- database connectivity
- kill-switch status
- recent failures

Failures must be actionable and fail closed for trading simulation when evidence is unsafe.

Do not require outbound notification services in Phase 3; persist alert-worthy events so notification channels can be added later without coupling them to trading logic.

---

## 15. Testing and CI

Preserve all Phase 1 and Phase 2 tests.

Add tests for at least:

- forward-only chronology
- frozen trial configuration
- no retroactive threshold edits
- idempotent incremental ingestion
- stale/gapped data lockout
- scheduler/cycle idempotency
- crash/restart recovery
- duplicate order/fill prevention
- risk-budget enforcement
- multiple-strategy accounting
- lifecycle transitions
- minimum-evidence qualification
- drift/degradation pause/fail rules
- regime no-lookahead behaviour
- replay vs genuine-forward isolation
- API GET-only boundary
- no live execution surface

Run and fix the complete quality suite:

```bash
ruff format --check .
ruff check .
mypy app scripts
python -m scripts.check_no_live_execution
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
python -m pip check
pip-audit
```

Keep secret detection and GitHub CI passing.

---

## 16. Phase 3 completion definition

Phase 3 is complete when the repository can safely create frozen forward trials, incrementally collect current read-only market data, execute restart-safe idempotent PAPER cycles, compare multiple trials/strategies against benchmarks, enforce portfolio risk budgets, detect degradation, and accumulate uncontaminated forward evidence over time.

The implementation must remain incapable of live-money trading.

A qualifying strategy is not required for completion.

---

## Completion report

At completion report:

1. architecture changes
2. files and migrations added/changed
3. provider/current-data behaviour
4. forward-trial freeze/contamination controls
5. scheduler/idempotency/recovery design
6. lifecycle qualification/pause/fail rules
7. risk-budget design
8. drift/degradation design
9. replay demonstration results
10. genuine forward trials started, if any, and why they are not yet statistically conclusive
11. tests, coverage, lint/type/security/audit results
12. known limitations
13. explicit confirmation that no live execution capability exists
14. recommended Phase 4 milestone

Do not implement real-money trading under any circumstances in Phase 3.
