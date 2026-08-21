# Phase 4 — Adaptive Research Factory and Regime-Aware Paper Portfolio

## Objective

Extend the completed Phase 3 Forward PAPER Observatory into a continuously operating, bounded research factory that can generate new candidate strategies from approved building blocks, evaluate them rigorously, admit only sufficiently robust candidates into new forward-paper challenger trials, and compare/allocate among qualified PAPER strategies using predeclared regime-aware policies.

Phase 4 remains research and simulation only. It must remain physically incapable of placing a real-money order or moving money.

The core question is:

> Can the laboratory repeatedly discover and govern new strategies that survive realistic historical validation and then continue to demonstrate robust forward PAPER behaviour without contaminating active trials or weakening risk controls?

Do not optimise for headline return. Prefer robustness, benchmark-relative performance, drawdown control, diversification, evidence quality, and reproducibility.

---

# 1. Permanent safety boundary

`TradingMode` must remain limited to:

- `BACKTEST`
- `PAPER`

There must be no `LIVE` mode.

Do not implement, enable, stub, or request credentials for:

- live brokerage or exchange order submission
- broker/exchange trading credentials
- deposits, withdrawals, transfers, or account funding
- leverage or margin
- options or futures execution
- borrowed-asset short selling
- copy trading or customer trading
- autonomous movement of money
- autonomous modification of the Risk Engine
- an LLM directly deciding or transmitting trades

Networking is permitted only inside explicitly approved read-only market-data provider modules using safe read-only methods.

No broker/exchange trading SDK is required.

Preserve and strengthen `scripts/check_no_live_execution.py` so CI fails if an execution/funding surface, trading SDK, unsafe HTTP method, external order transport, credential surface, or unsafe mode appears.

`QUALIFIED_FORWARD`, `CHAMPION`, `CHALLENGER`, or any equivalent Phase 4 state is PAPER/research status only and must never unlock live execution.

---

# 2. Preserve the Phase 1–3 baseline

Preserve all merged behaviour from Phases 1, 2, and 3, including:

- immutable strategy versions and experiment records
- genuine GET-only historical/current market data
- content-addressed/checksummed dataset provenance
- multi-asset long-only cash portfolio accounting
- realistic costs, spread and slippage
- independent immutable/versioned Risk Engine policies
- bounded research
- multiple-testing diagnostics
- deterministic regime analysis
- persistent restart-safe PAPER simulation
- immutable forward-trial manifests
- strict separation of `GENUINE_FORWARD` and `REPLAY`
- forward-trial lifecycle governance
- drift/degradation diagnostics
- champion/challenger read models
- bearer-protected GET-only private dashboard APIs
- complete audit/event persistence

Do not rewrite working architecture unless necessary to implement Phase 4 safely.

---

# 3. Research generations

Add a first-class immutable `ResearchGeneration` concept.

Each generation must record at minimum:

- generation ID
- generation number/version
- parent generation if any
- research cutoff timestamp
- immutable historical dataset IDs
- universe versions
- approved strategy grammar/catalogue version
- approved indicator catalogue version
- parameter bounds
- candidate budget
- compute/research budget
- benchmark definitions
- cost assumptions
- risk policy version
- validation policy version
- multiple-testing policy
- random seed(s)
- code revision
- created timestamp
- completion timestamp/status

A completed generation is immutable.

Re-running a generation with identical inputs must either reproduce the same candidate identities/results or fail loudly if deterministic equivalence cannot be achieved.

---

# 4. Approved strategy grammar

Create a bounded, owner-controlled strategy grammar/candidate catalogue.

Candidate generation may combine only approved components such as:

- moving-average/trend filters
- momentum/rate-of-change signals
- breakouts
- mean reversion
- volatility filters
- volatility targeting within cash-only PAPER limits
- regime filters
- time-based exits
- stop/exit policies already supported safely
- approved portfolio weighting/allocation rules

The grammar must define explicit parameter ranges and valid combinations.

Do not allow candidate generation to write or execute arbitrary Python/source code.

Do not allow an LLM to create executable trading logic dynamically.

If an LLM is ever used for research summaries, it may only summarize deterministic results and must not control strategy signals, execution, risk, qualification, or allocation.

Every candidate must be representable as an immutable `StrategySpec` with complete lineage.

---

# 5. Candidate lineage and mutation

Support traceable candidate lineage.

Each candidate records:

- immutable strategy ID/version
- generation ID
- parent candidate/strategy where applicable
- creation mechanism
- exact parameter/indicator changes
- creation reason
- complete strategy fingerprint/hash

Permitted candidate creation mechanisms may include:

- bounded parameter grid
- deterministic random search with stored seed
- approved local mutation around robust parents
- approved crossover of compatible configuration-only parents
- regime-specific variants
- portfolio/ensemble combinations of approved strategies

No self-modifying executable code is permitted.

Mutation/crossover must remain configuration-only and bounded by the approved grammar.

---

# 6. Research cutoffs and contamination control

Each generation must use an explicit research cutoff timestamp.

A candidate may use only data available on or before its generation cutoff for discovery/tuning/validation.

Data after the cutoff may be used only for future out-of-sample/forward observation.

Active forward trials must never be retuned using observations collected after their start.

A later generation may incorporate earlier market history that has since become historical only if:

- the new generation has a new cutoff
- all candidate identities/versions are new
- active trials remain unchanged
- trial performance is not relabelled as historical validation for the same immutable candidate
- provenance clearly records what data was available at candidate creation time

Add tests specifically preventing forward-period leakage and trial contamination.

---

# 7. Stronger anti-overfitting controls

Strengthen the existing validation system for larger research batches.

Include appropriate, explainable controls such as:

- nested chronological train/validation/test or equivalent rolling evaluation
- walk-forward evaluation
- parameter-neighbourhood stability
- cross-instrument robustness
- regime robustness
- minimum trade/observation counts
- benchmark-relative evaluation
- turnover/cost sensitivity
- stress tests for higher fees/spread/slippage
- candidate-count accounting
- family/group accounting for related strategies
- multiple-testing/data-snooping diagnostics
- deflated or adjusted Sharpe-style diagnostics where justified
- probabilistic or deterministic fragility indicators where explainable

Do not add statistical metrics merely for appearance; document assumptions and limitations.

The final locked hold-out must remain untouched during tuning.

Do not lower acceptance thresholds because no candidate passes.

Zero retained candidates is valid.

---

# 8. Research scoring and gates

Create a Phase 4 research score/gate that prioritises:

1. out-of-sample evidence
2. benchmark-relative performance
3. drawdown and downside risk
4. parameter stability
5. cross-instrument robustness
6. regime robustness
7. cost/stress resilience
8. diversification value
9. adequate sample size
10. data-snooping/multiple-testing penalty

Return an explainable breakdown rather than a single opaque number.

Candidates should have research lifecycle states equivalent to:

- GENERATED
- RESEARCHING
- REJECTED_RESEARCH
- HOLDOUT_PENDING
- HOLDOUT_PASSED
- CHALLENGER_ELIGIBLE
- CHALLENGER_STARTED
- ARCHIVED

Names may be adapted to existing architecture.

Research state must remain separate from Phase 3 forward-trial lifecycle state.

---

# 9. Automated challenger admission

Implement a deterministic challenger-admission service.

A candidate may become a new PAPER forward challenger only when all configured historical research gates pass.

Admission must:

- create a new immutable Phase 3-compatible forward trial
- freeze all strategy/config/risk/cost/benchmark/allocation/qualification assumptions
- set a trial start after the research cutoff
- never reuse earlier out-of-sample data as genuine forward evidence
- record the exact reason each gate passed
- be idempotent

Automatic challenger creation is permitted because it remains PAPER-only.

It must never create a live account/order path.

Allow an owner policy to require manual approval before a challenger trial starts, but do not make manual approval necessary for deterministic PAPER-only testing if the existing architecture supports safe automation.

---

# 10. Champion/challenger governance

Extend Phase 3 champion/challenger governance.

A champion should not mean "best return".

Champion selection for PAPER research should consider only predeclared, explainable rules using sufficient forward evidence, including:

- benchmark-relative return
- risk-adjusted return
- drawdown
- evidence age/observation count
- regime coverage
- drift/degradation state
- turnover/cost burden
- diversification contribution
- stability of performance

Require a configurable minimum evidence level before a challenger can displace a champion.

Support "no champion" as a valid state.

A champion must not imply or unlock real-money use.

---

# 11. Regime-aware PAPER allocation

Implement an optional regime-aware PAPER meta-allocation layer.

It may allocate simulated capital only among eligible PAPER strategies using a frozen, versioned allocation policy.

Requirements:

- regime classification must use only information available at the decision timestamp
- no look-ahead
- no leverage
- no margin
- no negative cash
- respect all portfolio/strategy/asset concentration limits
- independent Risk Engine remains final authority
- allocation policy cannot modify Risk Engine limits
- allocation policy changes create a new policy version
- compare against simple static baselines such as equal-weight eligible strategies and cash/benchmark alternatives where appropriate

Support a conservative cash allocation when no strategy qualifies for a regime.

No forced investment requirement exists.

---

# 12. Ensemble / portfolio-of-strategies research

Support research into ensembles of approved strategies.

Evaluate:

- correlation of returns/signals
- overlap in exposures
- marginal contribution to portfolio drawdown
- diversification benefit
- concentration
- turnover/cost interaction
- regime complementarity

Prefer simpler ensembles when performance is statistically/economically similar.

Do not allow an ensemble to bypass per-strategy or portfolio risk controls.

---

# 13. Research scheduling and orchestration

Add restart-safe, idempotent orchestration for periodic research generations.

A scheduled research cycle should be able to:

1. verify current data health
2. establish/freeze a research cutoff
3. create immutable dataset references
4. instantiate a bounded generation
5. generate candidates
6. run historical research/validation
7. apply anti-overfitting diagnostics
8. run locked hold-out evaluation
9. retain/reject candidates
10. optionally admit eligible challengers
11. persist generation summary/audit events

Use leases/locks/idempotency keys consistent with Phase 3 patterns.

A failed cycle must be recoverable without duplicating generations or trials.

---

# 14. Research budget / data-snooping budget

Create explicit configurable limits for automated research, for example:

- maximum candidates per generation
- maximum strategy families
- maximum parameter combinations
- maximum generations per schedule period
- maximum retained candidates
- maximum simultaneous forward challengers

Persist these limits with the generation.

Record attempted/tested candidate counts and expose them in reports/read models.

Do not silently expand the search space after inspecting results.

---

# 15. Drift feedback without active-trial retuning

Phase 3 drift/degradation results may influence governance actions such as:

- watch
- pause
- fail
- retire
- reduce PAPER allocation under a predeclared policy

They must not mutate the active strategy.

If drift suggests a new variant should be researched, create a new future research-generation request with explicit lineage. The new candidate must go through the full research and new forward-trial process.

---

# 16. Genuine forward evidence remains authoritative

Preserve strict separation between:

- historical research
- locked historical hold-out
- replay/engineering test
- genuine forward PAPER evidence

Replay results must always remain labelled `REPLAY / ENGINEERING TEST` and must never qualify a candidate as forward-tested.

Historical backtest strength alone must not convert a strategy into a forward champion.

---

# 17. Persistence and migrations

Add SQLAlchemy models/Alembic migrations required for at least:

- research generations
- candidate lineage
- research/gate results
- hold-out results
- research budgets
- challenger admissions
- allocation-policy versions
- regime-aware PAPER allocation decisions
- ensemble metadata where implemented
- generation/cycle audit records

Maintain SQLite local usability and PostgreSQL-ready boundaries.

Use immutable records where appropriate.

---

# 18. CLI / owner operations

Add useful owner CLI commands for tasks equivalent to:

- create/run a bounded research generation
- list generations
- inspect generation results
- inspect candidate lineage
- evaluate/admit eligible challengers
- list champion/challenger state
- run regime-aware PAPER allocation cycle
- replay a Phase 4 research cycle deterministically for engineering verification

Exact command names should follow repository conventions.

Commands that mutate PAPER research state must remain local/private and must not expose real execution.

---

# 19. GET-only API/read models

Extend the private bearer-protected API with GET-only Phase 4 read models suitable for the Trading Research Lab dashboard, including where appropriate:

- research generation list/detail
- candidate funnel
- candidate lineage
- rejected/retained reasons
- hold-out results
- multiple-testing diagnostics
- research budget utilisation
- challenger admissions
- champion/challenger comparison
- regime-aware PAPER allocation state
- strategy/ensemble correlation and diversification
- current research-cycle health
- latest generation status
- audit/event history

Do not expose secrets.

Do not add live-trading endpoints.

Preserve the existing authentication/proxy pattern.

---

# 20. Reporting

Generate a machine-readable and human-readable Phase 4 demonstration report.

The demonstration may use deterministic replay/historical research to prove mechanics, but replay must remain explicitly labelled and cannot count as genuine forward evidence.

Report at minimum:

- generation inputs/cutoff
- candidate count/search-space budget
- rejection funnel
- retained candidates
- hold-out outcomes
- benchmark comparisons
- multiple-testing/fragility diagnostics
- candidate lineage
- any challenger trials created
- champion/challenger state
- regime-aware PAPER allocation demonstration
- portfolio risk checks
- zero-live-execution confirmation

Never claim historical/replay profitability predicts future returns.

---

# 21. Tests

Add comprehensive tests for at least:

- generation immutability/reproducibility
- candidate grammar bounds
- deterministic seeds
- lineage/fingerprints
- research cutoff enforcement
- forward-data contamination prevention
- nested chronological validation
- hold-out isolation
- candidate budget limits
- multiple-testing accounting
- cost/slippage stress
- challenger admission gates
- idempotent admission
- champion/challenger minimum-evidence rules
- no-champion case
- regime-aware allocation chronology
- no leverage/margin/negative cash
- Risk Engine final authority
- drift-to-new-generation lineage rather than active mutation
- replay/genuine-forward separation
- scheduling/idempotency/recovery
- API authentication and GET-only safety
- persistence/migrations
- no-live-execution safety scan

Preserve existing coverage gate or improve it.

---

# 22. Quality and security gates

Before completion run and fix all failures from:

```bash
ruff format --check .
ruff check .
mypy app scripts
python -m scripts.check_no_live_execution
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
python -m pip check
pip-audit
```

Also ensure:

- GitHub Actions CI passes
- secret detection passes
- no credentials are committed
- the worktree is clean
- no broker/exchange trading SDK is added
- approved network providers remain GET-only/read-only

Do not merely report failures. Fix them and rerun the checks.

---

# 23. Completion report

At completion report:

- architecture changes
- major files/modules added
- migrations
- research-generation design
- approved grammar/candidate-generation design
- anti-overfitting/multiple-testing controls
- candidate lineage
- challenger-admission logic
- champion/challenger governance
- regime-aware PAPER allocator
- ensemble/diversification analysis
- orchestration/recovery behaviour
- API/read models
- replay demonstration results
- any genuine forward challengers started
- test count and coverage
- lint/type/security/dependency results
- GitHub CI result
- commit SHA
- PR URL
- known limitations
- recommended Phase 5

Explicitly confirm:

> There is no live-money execution capability.

Do not proceed to real-money trading.
