# Backtesting Assumptions

## Information timing

A daily bar timestamp represents its close. Indicator and signal calculations at that timestamp may
use that bar and older bars, never a later bar. An order created from the signal can first execute on
a strictly later bar. The execution model raises on same-bar or backwards fills.

## Fill model

- Market orders reference the following bar's open.
- Buy fills add half the configured spread and slippage; sell fills subtract them.
- A buy limit is eligible when the following bar's low reaches the limit and cannot fill above it.
- A sell limit is eligible when the following bar's high reaches the limit and cannot fill below it.
- Intrabar path and queue position are unknown, so limit results remain approximate.
- No partial fill or volume participation model exists yet.

## Costs and accounting

Each result displays commission basis points, fixed fee, minimum commission, spread, and slippage.
The engine tracks cash, long position quantity, market value, realised/unrealised P&L, cash dividends,
equity, drawdown, fees, and slippage. Fractional quantity is allowed for research convenience.

Open positions are marked to the final adjusted close and are not unrealistically liquidated on the
same closing bar. Metrics therefore include final unrealised P&L, while trade statistics contain
completed round trips only.

## Analytics

Daily periods use 252 annual periods by default. The risk-free rate is zero. Volatility uses sample
standard deviation. Drawdowns are positive magnitudes in summary metrics. Recovery is `None` when
the final drawdown has not recovered. Taxes, borrowing, leverage, margin, shorting, options, futures,
and foreign-exchange translation are absent.

## Benchmark

The included benchmark is passive first-close-to-last-close buy-and-hold on the same canonical
asset. It is a transparent baseline rather than a promise that it is the best real-world benchmark.
