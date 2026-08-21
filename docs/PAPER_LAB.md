# Persistent Paper Laboratory

The paper laboratory is a local simulator. It has no broker account, credential, network transport,
external order destination, or live-money state. Only `TradingMode.PAPER` is accepted.

## Cycle operation

1. Load an existing paper account and an immutable verified dataset snapshot.
2. Check the owner kill switch and freshness for every required instrument.
3. Derive a deterministic cycle ID from account, dataset, and latest instrument timestamps.
4. Resume any locally pending simulated orders and fill them only from eligible later frozen bars.
5. Evaluate strategies and the independent Risk Engine, then persist new local orders or rejection
   reasons.
6. Persist fills, holdings/cash/equity snapshot, attribution, and audit events in one transaction.
7. Mark the cycle complete. A repeat returns the existing completed cycle without duplicating
   orders or fills.

A failed cycle records its error and may be retried under the same identity with an incremented
attempt counter. Database uniqueness constraints prevent duplicate cycle, order, and fill records.
The scheduler is a fixed-interval trigger around this same service; it adds no different execution
capability.

## Operational controls

Stale/future/missing data, the kill switch, risk-limit rejection, insufficient cash, or an invalid
snapshot blocks simulated work and is audited. Restart recovery reloads cash, positions, average
cost, and pending orders. The GET-only local API exposes accounts, cycles, orders, fills, and audit
records for inspection but cannot start a cycle or mutate an account.

Paper results are synthetic fills under simplified assumptions. They are not evidence that an order
could have filled in a real market and do not guarantee future profitability.
