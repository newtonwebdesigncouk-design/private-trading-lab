# Risk Model

The Risk Engine is independent of strategy and allocation logic. A strategy may request exposure;
it cannot approve that exposure or mutate frozen `RiskLimits`. Every portfolio and paper order is
evaluated individually against an immutable context snapshot before a local simulated fill.

## Controls

The engine rejects a proposed simulated order when any applicable control fails:

- the owner-controlled global kill switch is engaged;
- projected position, asset-class, gross portfolio, or correlated-cluster exposure exceeds its cap;
- the configured minimum cash reserve would be breached;
- period turnover, concurrent holding count, or trade-frequency limits are exceeded;
- daily/weekly loss or portfolio drawdown has reached its stop;
- price data is stale, future-dated, missing, or exhibits a configured abnormal gap;
- notional, price, quantity, weight, cash, or portfolio value is invalid.

The engine receives current holdings and risk measurements from the portfolio service. Strategies
cannot supply or overwrite those measurements. Limits are conservative research defaults, not
personal investment guidance.

## Portfolio statistics

Portfolio volatility is calculated from aligned asset-return covariance and current weights.
Correlation matrices use only the provided historical window. Marginal and component risk
contributions derive from the same covariance estimate, and the component contributions sum to
portfolio volatility subject to floating-point tolerance. A configurable correlation threshold
groups exposure for a conservative concentration cap.

These estimates are backward-looking and unstable with small samples or regime changes. Missing
history reduces the usable aligned window; it never authorizes a risk-limit bypass.

## Accounting invariants

The portfolio is long-only and cash-funded. Buys include commission, spread, and slippage in the
cash requirement. Quantity is reduced or the proposal rejected if it would create negative cash.
The reserve is checked after costs. Sells cannot exceed held quantity. Corporate-action processing
cannot create a short position. No leverage, margin, borrowing, derivatives, or foreign-exchange
funding is available.

## Loss controls and kill switch

Drawdown, daily and weekly P&L, turnover, and trade counts are portfolio-level state. The kill
switch blocks new simulated actions before a paper cycle begins and is rechecked by the Risk Engine
for each proposal. It cannot be disabled by a candidate, strategy, or API request.

Risk scoring and paper qualification remain separate. The score emphasizes drawdown and capital
preservation, while fixed qualification rules also require adequate samples, chronological
consistency, cost robustness, and benchmark evidence. High raw return alone cannot qualify a
strategy, and an empty qualification set is a valid outcome.
