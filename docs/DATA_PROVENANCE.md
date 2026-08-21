# Data Provenance and Versioning

## Provider contract

Historical providers declare their name, version, supported asset classes and intervals, adjustment
policy, and capabilities. Phase 2 capabilities are deliberately narrow: historical market data is
supported; account access, order submission, order cancellation, funding, authenticated trading,
and live execution are not. `app/data/providers/transport.py` permits only HTTP GET with bounded
timeouts and deterministic retry handling.

Yahoo Chart provides the genuine demonstration data. Stooq CSV is implemented behind the same
contract, but the current public endpoint can return a JavaScript proof-of-work page. Such a
response is recorded as invalid/partial data and ingestion fails closed; the laboratory does not
POST a challenge response or scrape around the boundary.

## Normalization

Each raw row is mapped to the canonical asset and OHLCV schema, converted to UTC, sorted, and
validated. Duplicate timestamps retain the first deterministic row and log an event. Invalid
OHLC/volume/non-finite rows are rejected and counted. Calendar-aware expected timestamps reveal
missing observations; provider truncation/partial responses and stale ranges remain visible in
diagnostics. Every correction is explicit rather than silent.

## Immutable snapshot identity

`DatasetIngestor` writes one canonical JSONL bar artifact per asset, an optional JSONL
corporate-action artifact, and `manifest.json`. SHA-256 is computed over raw provider values,
canonical bytes, action bytes, and the manifest payload. The dataset version is derived from data
content and policy; the directory name combines the configured prefix with that version.

If the same content already exists, ingestion verifies it and returns it without rewriting its
bytes or ingestion timestamp. A checksum mismatch is a hard failure. Downstream commands load by
dataset ID, verify every artifact, and never silently substitute new provider data.

The manifest contains:

- provider name/version and non-secret configuration;
- requested and actual date ranges, interval, assets, and asset classes;
- schema version, UTC policy, adjustment and corporate-action policy;
- per-asset raw/canonical/action checksums and row counts;
- duplicate, invalid, out-of-order, missing, partial-response, and stale diagnostics;
- ingestion timestamp, code revision, and manifest checksum.

## Adjustment policy

The example snapshot is `TOTAL_RETURN_ADJUSTED`. Yahoo adjusted close supplies a ratio used to
adjust each bar's OHLC consistently. Returned dividend and split events are frozen separately for
audit, but portfolio accounting does not reapply them. A future raw-price provider must declare
`RAW` and use the corporate-action module; mixing policies in one result is prohibited.

## Freshness and known limits

Freshness is measured against the latest required timestamp for every instrument and feeds the
Risk Engine and paper-cycle gate. It does not infer an exchange is open or fabricate a missing bar.
The built-in calendar handles daily weekday/holiday expectations for traditional assets and daily
continuity for crypto, but it is not yet a complete exchange schedule. Provider corrections can
produce a new snapshot ID, which is expected and preserves the prior snapshot.
