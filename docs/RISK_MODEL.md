# Risk Model

The Risk Engine is independent of strategy logic. A strategy may request exposure; it cannot approve
that exposure or mutate the engine's frozen `RiskLimits`.

Initial controls reject simulated/paper requests when any of these apply:

- the global `TRADING_KILL_SWITCH` is engaged;
- position, asset-class, or portfolio exposure would exceed its limit;
- daily/weekly simulated loss or portfolio drawdown has reached its limit;
- concurrent position or trade-frequency limits are reached;
- market data is stale, future-dated, or exhibits an abnormal configured move;
- notional or price is invalid.

Default limits are conservative research defaults, not universal investment guidance. They are
evaluated using a frozen context snapshot. Risk-reducing behavior and multi-asset correlation limits
need deeper modelling before any later phase.

The kill switch currently blocks new simulated actions. It is supplied at Risk Engine construction
from owner-controlled configuration. The bounded Research Engine receives neither the engine nor a
configuration writer, so generated candidates cannot edit their limits.

Risk score weighting gives drawdown/capital preservation the largest single component. Return,
benchmark advantage, stability, sample size, costs, consistency, volatility, Sharpe, and Sortino all
contribute; raw return cannot independently qualify a strategy.
