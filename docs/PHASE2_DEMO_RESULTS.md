# Phase 2 Genuine Historical Demonstration

## Reproduction

The demo uses the frozen Yahoo Chart snapshot `phase2-yahoo-demo-7e23dd823599693e`, owner universe
`phase2-demo-v1`, and observations from January 2020 through January 2025. It contains 1,827 BTC-USD
daily bars and 1,258 bars each for SPY and QQQ. The ETF action artifacts retain 20 distribution/split
events each. Snapshot validation reported zero invalid, duplicate, missing-expected, partial, or
stale observations.

Run:

```bash
python -m scripts.validate_dataset --dataset phase2-yahoo-demo-7e23dd823599693e
python -m scripts.run_phase2_demo --dataset phase2-yahoo-demo-7e23dd823599693e --universe phase2-demo-v1 --output reports/phase2_demo_report.json
```

The workflow evaluated moving-average crossover, momentum, mean-reversion, and breakout reference
families across SPY, QQQ, and BTC-USD; ran chronological train/development/locked-test evaluation,
walk-forward checks, doubled-cost stress, seeded perturbations, prefix-only regimes, and passive
comparisons; generated 12 hard-capped moving-average candidates; and ran a bounded long-only
multi-asset portfolio.

## Evidence, not a promotion

No generated candidate was selected for the locked holdout or admitted to paper observation. All 12
had a mean validation score below the fixed research threshold and failed to beat every instrument's
passive benchmark; 11 also missed the validation trade-count minimum. The locked candidate holdout
therefore remained unopened. This zero-selection result was not changed by relaxing thresholds.

Benjamini-Hochberg marked all approximate Sharpe p-values below its 5% diagnostic threshold, but
that did not override economic and robustness failures. The p-values assume independent stationary
returns and the candidates are correlated, so they are explicitly treated as a warning diagnostic,
not qualification evidence.

The strongest individual reference result by risk-first score was BTC-USD Breakout at 72.00. On its
held-out 2024 segment it returned 5.71%, Sharpe 1.00, maximum drawdown 1.83%, and 23 trades, versus
111.53% for passive BTC-USD. It failed paper qualification for score, sample size, walk-forward
consistency, and benchmark underperformance. Every other reference result was also rejected.

## Portfolio and benchmarks

The bounded long-only portfolio started with USD 100,000 and returned 56.70% over the full snapshot:
9.42% annualized return, 11.56% annualized volatility, 0.84 Sharpe, 1.23 Sortino, 21.86% maximum
drawdown, and 144 completed trades. It incurred USD 396.57 in fees and USD 489.11 in modeled
slippage. Turnover was 10.67 times initial capital. Maximum invested exposure was 78.85%; cash never
fell below USD 24,471.63, so the run used neither leverage nor negative cash.

| Benchmark | Total return | Maximum drawdown | Sharpe | Portfolio excess return |
| --- | ---: | ---: | ---: | ---: |
| Buy/hold BTC-USD | 1,237.48% | 76.63% | 1.13 | -1,180.77% |
| Buy/hold QQQ | 143.86% | 35.12% | 0.83 | -87.16% |
| Buy/hold SPY | 94.58% | 33.72% | 0.74 | -37.88% |
| Equal-weight universe | 491.98% | 63.79% | 1.04 | -435.27% |
| Cash at 0% | 0.00% | 0.00% | 0.00 | +56.70% |

This is a deliberately small, survivorship-biased universe and an unusually strong historical
period for its assets. Total-return-adjusted data, zero cash yield, simplified fills, and lack of tax
or FX effects further limit interpretation. Historical, backtest, and paper results do not guarantee
future profitability.
