# Phase 3 Deterministic Replay Demonstration

## What was demonstrated

The checked-in `reports/phase3_replay_report.json` uses the immutable Phase 2 snapshot
`phase2-yahoo-demo-7e23dd823599693e`. It reveals SPY, QQQ and BTC-USD observations from 1 December
2024 through 1 January 2025 one timestamp at a time to three pre-frozen strategy trials. The source,
trial manifests, evidence and database rows all carry `REPLAY` provenance.

The run produced 32 immutable evidence updates and 32 completed PAPER cycles. The first cycle was
deliberately marked failed before portfolio mutation and was then retried under the same cycle ID;
its persisted retry count is one and it completed once. Delivering the final evidence again returned
`DUPLICATE` with `processed=false`, adding no order, fill, observation or P&L.

The demonstration exercises next-bar local fills, fixed strategy sleeves and reserve, shared risk
checks, benchmark-relative metrics, point-in-time regimes, rolling degradation, lifecycle decisions,
champion/challenger comparison, audit persistence and operational read models. Run:

```bash
python -m scripts.run_phase3_replay --output reports/phase3_replay_report.json
```

The three trial end states were `PAUSED_RISK` for the BTC-USD moving-average and SPY momentum
fixtures and `OBSERVING` for QQQ breakout. None qualified. The simulated portfolio ended at USD
298,361.13 from USD 300,000 (-0.55%), with USD 198,100.84 cash, 33.60% gross exposure and 2.64%
maximum observed portfolio drawdown. Its frozen-weight passive benchmark returned -1.14%, so the
mechanical portfolio excess was +0.59 percentage points. These short-window numbers are included
for regression reproducibility, not promotion.

## Interpretation

This short window exists to verify engineering mechanics. Its trial ranking, return, state and
degradation outcomes are not genuine forward performance claims, are not investment guidance, and
must not be used to retune these trial identities. The frozen minimum-evidence rules may leave every
trial observing, paused, failed or retired; zero `QUALIFIED_FORWARD` outcomes is valid.

No genuine forward trial was started by this implementation. Phase 2 selected zero strategies for
paper qualification, and automatically relaxing that decision or backdating a trial would violate
the contamination boundary. An owner may explicitly create new, frozen future-start trials later.

The replay used no external trading service. Supported modes remained `BACKTEST` and `PAPER`; all
orders/fills were local simulation records and external order transmission remained false.
