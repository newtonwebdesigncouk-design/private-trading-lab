"""Restart, idempotency, freshness, failure retry, and kill-switch paper tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.database import Base, create_database_engine, session_factory
from app.database.tables import (
    PaperAuditRow,
    PaperCycleRow,
    PaperFillRow,
    PaperOrderRow,
    PaperPortfolioSnapshotRow,
)
from app.models.enums import AssetClass
from app.models.market import Asset, MarketBar
from app.models.strategy import StrategySpec
from app.paper_trading import (
    FixedIntervalPaperScheduler,
    PaperCycleStatus,
    PersistentPaperLab,
    PersistentPaperRepository,
)
from app.risk import RiskEngine, RiskLimits
from app.strategies.base import Strategy


class AlwaysLongStrategy(Strategy):
    def desired_exposure(self, available_history: tuple[MarketBar, ...]) -> float:
        return 1.0


class FailingStrategy(Strategy):
    def desired_exposure(self, available_history: tuple[MarketBar, ...]) -> float:
        raise RuntimeError("deterministic strategy failure")


def paper_strategy(asset: Asset, *, failing: bool = False) -> Strategy:
    spec = StrategySpec(
        strategy_id=f"paper-{asset.symbol.lower()}",
        version=1,
        name="Persistent paper fixture",
        description="Always requests a bounded long allocation",
        asset_class=asset.asset_class,
        permitted_assets=(asset.symbol,),
        timeframe="1d",
        indicators=(),
        entry_conditions=("always",),
        exit_conditions=("never",),
    )
    return FailingStrategy(spec) if failing else AlwaysLongStrategy(spec)


def paper_bars(asset: Asset, count: int) -> tuple[MarketBar, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return tuple(
        MarketBar(
            timestamp=start + timedelta(days=index),
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            adjusted_close=101 + index,
            volume=1000,
            asset=asset,
            source="immutable-fixture",
            interval="1d",
        )
        for index in range(count)
    )


def paper_repository(tmp_path: Path) -> tuple[PersistentPaperRepository, object]:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'paper.db'}")
    Base.metadata.create_all(engine)
    return PersistentPaperRepository(session_factory(engine)), engine


def test_paper_cycles_are_persistent_restart_safe_and_idempotent(tmp_path: Path) -> None:
    repository, database_engine = paper_repository(tmp_path)
    repository.create_account("paper", starting_cash=10_000)
    asset = Asset(symbol="TEST", asset_class=AssetClass.EQUITY, exchange="TEST")
    risk = RiskEngine(RiskLimits(stale_after=timedelta(days=2)))
    first_lab = PersistentPaperLab(repository, risk)
    first_bars = paper_bars(asset, 2)
    first = first_lab.run_cycle(
        "paper",
        "snapshot-v1",
        {asset.symbol: paper_strategy(asset)},
        {asset.symbol: first_bars},
        evaluation_timestamp=first_bars[-1].timestamp,
    )
    assert first.status is PaperCycleStatus.COMPLETED
    assert first.processed
    assert first.orders
    assert not first.fills
    assert repository.load_account("paper").pending_orders

    duplicate = first_lab.run_cycle(
        "paper",
        "snapshot-v1",
        {asset.symbol: paper_strategy(asset)},
        {asset.symbol: first_bars},
        evaluation_timestamp=first_bars[-1].timestamp,
    )
    assert duplicate.status is PaperCycleStatus.DUPLICATE
    assert not duplicate.processed

    restarted_lab = PersistentPaperLab(repository, risk)
    second_bars = paper_bars(asset, 3)
    second = restarted_lab.run_cycle(
        "paper",
        "snapshot-v2",
        {asset.symbol: paper_strategy(asset)},
        {asset.symbol: second_bars},
        evaluation_timestamp=second_bars[-1].timestamp,
    )
    assert second.status is PaperCycleStatus.COMPLETED
    assert second.fills
    assert second.account.positions[asset.symbol].quantity > 0
    assert second.account.cash >= 0
    restored = repository.load_account("paper")
    assert restored.account.positions
    assert not restored.pending_orders

    sessions = session_factory(database_engine)  # type: ignore[arg-type]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(PaperCycleRow)) == 2
        assert session.scalar(select(func.count()).select_from(PaperOrderRow)) == 1
        assert session.scalar(select(func.count()).select_from(PaperFillRow)) == 1
        assert session.scalar(select(func.count()).select_from(PaperPortfolioSnapshotRow)) == 2
        assert session.scalar(select(func.count()).select_from(PaperAuditRow)) >= 4


def test_paper_cycle_freshness_and_kill_switch_are_audited(tmp_path: Path) -> None:
    repository, _ = paper_repository(tmp_path)
    repository.create_account("stale", starting_cash=10_000)
    repository.create_account("blocked", starting_cash=10_000, kill_switch=True)
    asset = Asset(symbol="TEST", asset_class=AssetClass.EQUITY, exchange="TEST")
    bars = paper_bars(asset, 2)
    stale = PersistentPaperLab(
        repository, RiskEngine(RiskLimits(stale_after=timedelta(hours=1)))
    ).run_cycle(
        "stale",
        "snapshot-stale",
        {asset.symbol: paper_strategy(asset)},
        {asset.symbol: bars},
        evaluation_timestamp=bars[-1].timestamp + timedelta(hours=2),
    )
    assert stale.status is PaperCycleStatus.COMPLETED
    assert not stale.orders
    assert any(event["event_type"] == "ORDER_REJECTED" for event in stale.audit_events)
    blocked = PersistentPaperLab(repository, RiskEngine()).run_cycle(
        "blocked",
        "snapshot-blocked",
        {asset.symbol: paper_strategy(asset)},
        {asset.symbol: bars},
        evaluation_timestamp=bars[-1].timestamp,
    )
    assert blocked.status is PaperCycleStatus.BLOCKED
    assert not blocked.orders and not blocked.fills
    assert any(event["event_type"] == "PAPER_CYCLE_BLOCKED" for event in blocked.audit_events)


def test_failed_cycle_is_logged_and_can_retry_deterministically(tmp_path: Path) -> None:
    repository, database_engine = paper_repository(tmp_path)
    repository.create_account("retry", starting_cash=10_000)
    asset = Asset(symbol="TEST", asset_class=AssetClass.EQUITY, exchange="TEST")
    bars = paper_bars(asset, 2)
    lab = PersistentPaperLab(repository, RiskEngine(RiskLimits(stale_after=timedelta(days=2))))
    with pytest.raises(RuntimeError, match="deterministic strategy failure"):
        lab.run_cycle(
            "retry",
            "snapshot-retry",
            {asset.symbol: paper_strategy(asset, failing=True)},
            {asset.symbol: bars},
            evaluation_timestamp=bars[-1].timestamp,
        )
    retried = lab.run_cycle(
        "retry",
        "snapshot-retry",
        {asset.symbol: paper_strategy(asset)},
        {asset.symbol: bars},
        evaluation_timestamp=bars[-1].timestamp,
    )
    assert retried.status is PaperCycleStatus.COMPLETED
    sessions = session_factory(database_engine)  # type: ignore[arg-type]
    with sessions() as session:
        cycle = session.get(PaperCycleRow, retried.cycle_id)
        assert cycle is not None
        assert cycle.retry_count == 1
        assert cycle.error is None


def test_scheduler_abstraction_is_deterministic() -> None:
    scheduler = FixedIntervalPaperScheduler(timedelta(hours=24))
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    assert scheduler.next_expected_cycle(timestamp) == timestamp + timedelta(days=1)
    with pytest.raises(ValueError, match="positive"):
        FixedIntervalPaperScheduler(timedelta(0))
