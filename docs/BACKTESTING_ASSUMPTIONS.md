# Backtesting Assumptions

## Information timing

A canonical daily timestamp represents when the complete daily bar is available. Indicator,
regime, and signal calculations at time `t` use only bars with timestamps at or before `t`.
Provider dates are never treated as advance knowledge: Yahoo daily observations are shifted to the
following UTC midnight. A signal-generated order can first execute at a strictly later common
portfolio timestamp. Dataset splits are chronological and never shuffled.

Point-in-time regime features use only the prefix ending at their timestamp. Research selection may
inspect train and validation data, not the final holdout. That holdout is evaluated only for the
candidate IDs selected before it is opened.

## Fill model

- Market orders reference the following available bar's open.
- Buy fills add half the configured spread and slippage; sells subtract them.
- Commission basis points, fixed fees, and minimum commission are charged explicitly.
- A buy limit is eligible when a later bar's low reaches the limit and cannot fill above it; a sell
  limit uses the later bar's high and cannot fill below it.
- Assets may have different sessions. The engine uses a union clock and acts only when the required
  current/next asset bar exists.
- There is no intrabar path, queue-priority, volume-participation, market-impact, latency, or partial
  fill model, so results remain optimistic for less liquid instruments.

## Multi-asset accounting

The portfolio records USD cash, long quantity, average cost, market value, realized and unrealized
P&L, dividends, fees, slippage, turnover, total equity, drawdown, and asset/strategy/class
attribution. Fractional quantities are allowed for research convenience. Buys must be fully
cash-funded after costs and the configured reserve; sells cannot exceed holdings. Positions are
marked at the last known close at a common timestamp and are not force-liquidated on the final bar.

Allocation methods are bounded transformations rather than optimizers: equal weight, owner-fixed
weight, inverse trailing volatility, and non-negative score weight. Per-position, per-class, gross,
cash-reserve, correlated-exposure, and turnover caps still apply after allocation. Drift can change
weights between rebalances but cannot introduce borrowing or short exposure.

## Corporate actions and adjusted prices

The Yahoo adapter stores total-return-adjusted OHLC. Its adjustment factor reflects Yahoo's
adjusted-close series, including the effect of splits and cash distributions. Dividend and split
events are retained in separate provenance artifacts but are not applied again to a portfolio that
uses those bars; applying them twice would overstate return. The generic corporate-action module can
apply raw split ratios and cash dividends when a future provider explicitly declares a raw-price
policy.

Only announced actions returned by the provider are represented. Merger consideration, spin-offs,
rights, symbol changes, delistings, withholding tax, and action revisions are not fully modeled.

## Analytics and benchmarks

Daily traditional-market calculations use 252 annual periods; the demo's common mixed-asset clock
uses the configured period count consistently. The risk-free and cash interest rates are zero.
Volatility uses sample standard deviation. Drawdown is a positive magnitude. Recovery is `None`
when the final peak has not been recovered.

Portfolio results are compared with buy-and-hold for every universe asset, an equal-weight universe
portfolio, and cash. Reports include total/annualized return, volatility, Sharpe, Sortino, maximum
drawdown, recovery, downside-risk difference, tracking difference, and turnover/cost difference.
Benchmarks are transparent baselines, not claims that an instrument is investable or appropriate.

## Universe and survivorship

Universes are explicit and versioned, with inclusion reasons, dates, categories, provider symbols,
and benchmark mappings. The Phase 2 demo is a present-day owner list of three liquid instruments,
not a historical constituent database. Its results therefore have survivorship and selection bias.
They exclude delisted alternatives and do not answer what could have been selected at each past
date.

## Research safeguards and limitations

Candidate generation is deterministic, structured, seeded, and hard-capped. Every candidate is
evaluated consistently across configured instruments with train/validation splits, walk-forward
folds, doubled cost assumptions, local price perturbation, minimum sample rules, passive
benchmarks, and fixed paper-qualification thresholds. Candidate count and the full space size are
reported. Failures and zero-selection batches are retained as evidence.

Benjamini-Hochberg controls the reported false-discovery rate over approximate Sharpe p-values.
Those p-values assume independent, stationary returns; strategy returns and parameter neighbours
are correlated and non-stationary, so the result is a diagnostic rather than proof of an edge. It
does not replace a locked holdout, economic reasoning, robustness checks, or prolonged paper
observation.

Taxes, inflation, foreign-exchange conversion, borrowing, leverage, margin, shorting, derivatives,
and live execution are absent. Historical, backtest, and paper results do not guarantee future
profitability.

## Forward observation and replay

Genuine Phase 3 observations begin at the manifest's declared UTC start. Earlier frozen snapshot
bars may warm indicators, but cannot become forward observations, elapsed evidence, or lifecycle
credit. A current-data catch-up records unseen chronology; only the newest safe bar may advance the
PAPER execution state, avoiding a claim that old backfilled decisions occurred in real time.

Regime labels are recomputed from the prefix through each observed bar. Forward signals use that
same prefix, and market orders retain the Phase 1/2 next-bar-open cost model. Benchmark return uses
the frozen buy-and-hold/cash definition; portfolio comparison uses original trial weights plus
zero-return reserve. Rolling degradation uses only committed forward snapshots.

The engineering replay reveals a checksummed Phase 2 snapshot one timestamp per cycle and records
mandatory `REPLAY` provenance in a separate database/evidence stream. Its results demonstrate
idempotency, recovery, accounting, drift, and lifecycle mechanics; they are not forward performance
claims and cannot qualify a genuine trial.
