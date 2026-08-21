# Private Trading Laboratory

A private, single-user laboratory for testing whether systematic strategies exhibit robust,
risk-adjusted performance after realistic costs. Phase 2 adds genuine provider-backed historical
data, immutable datasets, multi-asset portfolios, bounded research batches, and persistent paper
simulation. It remains simulation-only: no live execution mode, order transmitter, broker or
exchange SDK, credential field, funding path, leverage, margin, derivatives, or short selling
exists.

Reference strategies are engineering fixtures, not investment recommendations. Historical,
backtest, and paper results do not guarantee future profitability.

## Safety boundary

- `TradingMode` is a closed enum containing only `BACKTEST` and `PAPER`.
- Approved provider modules make unauthenticated HTTP `GET` requests for historical market data
  only. Provider capabilities explicitly declare that account, order, and streaming operations are
  unsupported.
- Strategies request exposure; the immutable, independent Risk Engine permits or rejects it.
- The paper broker fills locally against snapshotted/replayed bars and persists every decision.
- No production dependency is a broker/exchange SDK and no API endpoint submits an order.
- `scripts/check_no_live_execution.py` rejects execution/funding surfaces, credential settings,
  trading SDKs, unsafe modes, non-GET provider requests, or networking outside approved data
  modules.

See [AGENTS.md](AGENTS.md), [docs/PHASE2_SPEC.md](docs/PHASE2_SPEC.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md),
and [docs/RISK_MODEL.md](docs/RISK_MODEL.md).

## Quick start

Python 3.12 or later is required.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
python -m scripts.run_backtest
```

## Phase 2 genuine-data workflow

The checked-in example universe contains SPY, QQQ, and BTC-USD. Yahoo Chart is the demonstration
source; it is public, credential-free, and read-only. Network access occurs only during ingestion.
Every later command operates on the frozen dataset identifier.

```bash
python -m scripts.ingest_market_data --config config/phase2_demo.json
python -m scripts.list_datasets --snapshot-root data/snapshots
python -m scripts.validate_dataset --dataset phase2-yahoo-demo-049a182908354067
python -m scripts.run_portfolio_backtest --dataset phase2-yahoo-demo-049a182908354067 --universe phase2-demo-v1
python -m scripts.run_research --dataset phase2-yahoo-demo-049a182908354067 --universe phase2-demo-v1
python -m scripts.run_phase2_demo --dataset phase2-yahoo-demo-049a182908354067 --universe phase2-demo-v1
```

The demo writes `reports/phase2_demo_report.json`; the checked-in findings are summarized in
[docs/PHASE2_DEMO_RESULTS.md](docs/PHASE2_DEMO_RESULTS.md). The snapshot ID is content-derived, so
a provider revision may legitimately produce a new ID. Use the ID printed by ingestion in that
case.

Persistent paper simulation is an explicit, local cycle:

```bash
python -m scripts.run_paper_cycle --account phase2-demo --dataset phase2-yahoo-demo-049a182908354067
```

The cycle is restart-safe and idempotent for its account/dataset/timestamp identity. It loads only
frozen bars, checks freshness and the kill switch, restores pending simulated orders, records local
fills, and commits the account snapshot and audit trail atomically. Re-running the same completed
cycle performs no duplicate work.

## Local read API

```bash
uvicorn app.api.main:app --reload
```

Alongside the Phase 1 strategy endpoints, Phase 2 exposes GET-only read models under `/data`,
`/research`, `/portfolio`, and `/paper`. Interactive documentation is at `/docs`. The API has no
action endpoint.

## Quality and safety gates

```bash
ruff format --check .
ruff check .
mypy app scripts
python -m scripts.check_no_live_execution
pytest --cov=app --cov-report=term-missing --cov-fail-under=80
python -m pip check
pip-audit
```

## Architecture at a glance

```text
approved GET-only provider -> normalize/validate -> immutable checksummed snapshot
                                                        |
             versioned universe + strategy specs -------+
                              |                          |
                              v                          v
                    bounded research            multi-asset portfolio
                    train -> validation          allocator -> risk -> next bar
                    -> locked holdout                    |
                              |                          v
                              +--> benchmark/regime/attribution reports

frozen snapshot -> idempotent paper cycle -> local simulated orders/fills -> SQL audit
```

SQLAlchemy 2 and Alembic back persistence. SQLite is the local default; the schema and transaction
boundaries remain PostgreSQL-ready.

## Reproducibility and limitations

Dataset manifests record provider/configuration, requested and actual ranges, canonical schema,
timezone and adjustment policies, per-file SHA-256 checksums, normalization diagnostics, ingestion
time, and code revision. Research records add the universe version, candidate-space size, seed,
chronological split, costs, benchmarks, regimes, scores, lifecycle outcome, and rejection reasons.

Owner-configured universes avoid hidden selection logic but have survivorship bias: the Phase 2
example uses instruments known at configuration time and is not a point-in-time constituent
history. Yahoo adjusted OHLC embeds splits and distributions; action events are retained as
provenance and are not applied again. Daily exchange calendars are conservative and do not yet
model every irregular closure. There is no FX conversion, tax model, volume participation, partial
fill model, intraday feed, or live broker integration.
