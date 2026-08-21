"""Run the frozen Phase 3 engineering replay and emit its auditable report."""

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.data.snapshots import DatasetSnapshotStore
from app.database import Base, create_database_engine, session_factory
from app.database import tables as database_tables  # noqa: F401
from app.forward.evidence import ForwardEvidenceStore, evidence_stream_id
from app.forward.orchestrator import ForwardCycleOrchestrator
from app.forward.portfolio import ForwardPortfolioEngine
from app.forward.read_model import ForwardReadModel
from app.forward.replay import run_deterministic_replay
from app.forward.repository import ForwardRepository
from app.models.enums import ForwardCycleStatus, ObservationProvenance
from app.risk import RiskEngine
from app.strategies.reference import strategy_from_spec
from scripts.phase2_common import strategy_for_asset
from scripts.phase3_common import replay_trial_manifest, revision


def _serialisable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"cannot serialise {type(value).__name__}")


def _has_retry(item: dict[str, object]) -> bool:
    value = item.get("retry_count")
    return isinstance(value, int) and value > 0


def build_report(
    *,
    dataset_id: str,
    snapshot_root: Path,
    work_root: Path,
    start: datetime,
    end: datetime,
    code_revision: str,
) -> dict[str, Any]:
    snapshot_store = DatasetSnapshotStore(snapshot_root)
    source_manifest = snapshot_store.load_manifest(dataset_id)
    bars = {
        item.asset.symbol: snapshot_store.load_bars(dataset_id, item.asset.symbol)
        for item in source_manifest.instruments
    }
    engine = create_database_engine(f"sqlite:///{(work_root / 'phase3-replay.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = ForwardRepository(session_factory(engine))
    assets = {item.asset.symbol: item.asset for item in source_manifest.instruments}
    family = {"SPY": 1, "QQQ": 3, "BTCUSD": 0}
    strategies = {}
    manifests = []
    portfolio_id = f"phase3-replay-{source_manifest.dataset_version}"
    for symbol in sorted(assets):
        strategy = strategy_for_asset(assets[symbol], family[symbol])
        manifest = replay_trial_manifest(
            portfolio_id=portfolio_id,
            strategy=strategy,
            asset=assets[symbol],
            start=start,
            code_revision=code_revision,
            source_dataset_id=dataset_id,
        )
        repository.create_trial(manifest)
        strategies[manifest.trial_id] = strategy_from_spec(manifest.strategy)
        manifests.append(manifest)
    trials = tuple(repository.get_trial(item.trial_id) for item in manifests)
    portfolio_engine = ForwardPortfolioEngine(RiskEngine(manifests[0].risk_policy.limits))
    orchestrator = ForwardCycleOrchestrator(repository, portfolio_engine)
    evidence_store = ForwardEvidenceStore(work_root / "evidence")
    stream_id = evidence_stream_id(
        portfolio_id,
        ObservationProvenance.REPLAY,
        tuple(assets.values()),
        manifests[0].data_policy,
    )
    results = run_deterministic_replay(
        repository=repository,
        orchestrator=orchestrator,
        evidence_store=evidence_store,
        stream_id=stream_id,
        source_dataset_id=dataset_id,
        trials=trials,
        strategies=strategies,
        bars_by_symbol=bars,
        start=start,
        end=end,
        code_revision=code_revision,
    )
    read_model = ForwardReadModel(repository, kill_switch=False)
    trial_items = [
        read_model.trial_detail(item.manifest.trial_id)
        for item in repository.list_trials(portfolio_id=portfolio_id)
    ]
    cycles = repository.cycles(portfolio_id)
    completed = [item for item in cycles if item["status"] == ForwardCycleStatus.COMPLETED.value]
    recovery = next((item for item in cycles if _has_retry(item)), None)
    latest_manifest = evidence_store.latest_manifest(stream_id)
    report: dict[str, Any] = {
        "report_version": "phase3-replay-v1",
        "generated_at": datetime.now(UTC),
        "code_revision": code_revision,
        "provenance": ObservationProvenance.REPLAY.value,
        "source_dataset_id": dataset_id,
        "observation_window": {"start": start, "end": end},
        "genuine_forward_trials_started": 0,
        "trials": {
            "items": trial_items,
            "count": len(trial_items),
            "qualified_forward_count": sum(
                item["state"] == "QUALIFIED_FORWARD" for item in trial_items
            ),
            "note": "Replay states verify mechanics and are not genuine forward evidence.",
        },
        "portfolio": read_model.portfolio(portfolio_id),
        "performance": read_model.performance(portfolio_id),
        "health": read_model.health(portfolio_id),
        "cycles": {
            "completed": len(completed),
            "failed": sum(item["status"] == "FAILED" for item in cycles),
            "blocked": sum(item["status"] == "BLOCKED" for item in cycles),
            "last_ten": list(cycles[-10:]),
        },
        "data_quality": read_model.data_quality(),
        "replay_verification": {
            "deterministic_seed": 1729,
            "evidence_updates": latest_manifest.sequence if latest_manifest else 0,
            "completed_cycles": len(completed),
            "retry_recovered": recovery is not None and recovery["status"] == "COMPLETED",
            "retry_count": recovery["retry_count"] if recovery else 0,
            "duplicate_was_no_op": bool(results and not results[-1].processed),
            "duplicate_status": results[-1].status.value if results else None,
            "same_cycle_engine": True,
        },
        "current_data_provider": {
            "production_adapter": "YahooReadOnlyProvider",
            "transport_method": "GET",
            "credentials_required": False,
            "enabled_by_default": False,
            "fail_closed_on_stale_partial_gap_or_future_data": True,
        },
        "safety": {
            "supported_modes": ["BACKTEST", "PAPER"],
            "external_order_transmission": False,
            "live_money_execution": False,
            "leverage_or_borrowing": False,
            "qualification_is_paper_only": True,
        },
    }
    payload = cast(
        dict[str, Any],
        json.loads(json.dumps(report, default=_serialisable, sort_keys=True)),
    )
    engine.dispose()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="phase2-yahoo-demo-7e23dd823599693e")
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--start", default="2024-12-01T00:00:00+00:00")
    parser.add_argument("--end", default="2025-01-01T00:00:00+00:00")
    parser.add_argument("--output", type=Path, default=Path("reports/phase3_replay_report.json"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="phase3-replay-") as temporary:
        report = build_report(
            dataset_id=args.dataset,
            snapshot_root=args.snapshot_root,
            work_root=Path(temporary),
            start=datetime.fromisoformat(args.start),
            end=datetime.fromisoformat(args.end),
            code_revision=revision(),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["replay_verification"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
