"""Deterministic, fully reported conversion from provider rows to canonical bars."""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.data.models import DataQualityDiagnostics, NormalisationEvent, RawMarketBar
from app.models.market import Asset, MarketBar


def normalise_bars(
    rows: Iterable[RawMarketBar],
    *,
    asset: Asset,
    source: str,
    interval: str,
    source_timezone: str = "UTC",
    expected_timestamps: Sequence[datetime] = (),
) -> tuple[tuple[MarketBar, ...], DataQualityDiagnostics]:
    """Sort, de-duplicate, validate, and report every deterministic transformation."""
    raw_rows = tuple(rows)
    zone = ZoneInfo(source_timezone)
    events: list[NormalisationEvent] = []
    normalised: dict[datetime, MarketBar] = {}
    invalid = 0
    duplicates = 0
    out_of_order = 0
    previous: datetime | None = None

    for raw in raw_rows:
        timestamp = raw.timestamp
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            timestamp = timestamp.replace(tzinfo=zone)
            events.append(
                NormalisationEvent(
                    event_type="TIMEZONE_ATTACHED",
                    timestamp=timestamp.astimezone(UTC),
                    detail=f"attached declared provider timezone {source_timezone}",
                )
            )
        timestamp = timestamp.astimezone(UTC)
        if previous is not None and timestamp < previous:
            out_of_order += 1
        previous = timestamp
        try:
            bar = MarketBar(
                timestamp=timestamp,
                open=raw.open,
                high=raw.high,
                low=raw.low,
                close=raw.close,
                adjusted_close=raw.adjusted_close,
                volume=raw.volume,
                asset=asset,
                source=source,
                interval=interval,
                dividend=raw.dividend,
            )
        except ValueError as exc:
            invalid += 1
            events.append(
                NormalisationEvent(
                    event_type="INVALID_ROW_REJECTED",
                    timestamp=timestamp,
                    detail=str(exc),
                )
            )
            continue
        if timestamp in normalised:
            duplicates += 1
            events.append(
                NormalisationEvent(
                    event_type="DUPLICATE_ROW_REJECTED",
                    timestamp=timestamp,
                    detail="kept the first canonical observation",
                )
            )
            continue
        normalised[timestamp] = bar

    bars = tuple(normalised[key] for key in sorted(normalised))
    canonical_timestamps = set(normalised)
    expected_utc = {
        (value.replace(tzinfo=zone) if value.tzinfo is None else value).astimezone(UTC)
        for value in expected_timestamps
    }
    missing = tuple(sorted(expected_utc.difference(canonical_timestamps)))
    if out_of_order:
        events.append(
            NormalisationEvent(
                event_type="ROWS_SORTED",
                detail=f"sorted {out_of_order} out-of-order observations",
            )
        )
    warnings: list[str] = []
    if missing:
        warnings.append(f"{len(missing)} expected timestamps are missing")
    if invalid:
        warnings.append(f"{invalid} invalid rows were rejected")
    diagnostics = DataQualityDiagnostics(
        input_rows=len(raw_rows),
        output_rows=len(bars),
        duplicate_rows=duplicates,
        invalid_rows=invalid,
        out_of_order_rows=out_of_order,
        missing_expected_timestamps=missing,
        partial_response=invalid > 0 or not bars,
        events=tuple(events),
        warnings=tuple(warnings),
    )
    return bars, diagnostics
