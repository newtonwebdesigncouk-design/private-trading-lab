"""Create a complete set of immutable genuine-forward PAPER trials from owner config."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.backtesting.models import CostAssumptions
from app.data.providers import YahooReadOnlyProvider
from app.data.snapshots import DatasetSnapshotStore
from app.database import Base, create_database_engine, session_factory
from app.forward.models import (
    ForwardBaselineProfile,
    ForwardBenchmarkDefinition,
    ForwardDataPolicy,
    ForwardDegradationPolicy,
    ForwardQualificationPolicy,
    ForwardRiskPolicy,
    ForwardTrialManifest,
)
from app.forward.orchestrator import ForwardCycleOrchestrator
from app.forward.portfolio import ForwardPortfolioEngine
from app.forward.repository import ForwardRepository
from app.models.enums import ObservationProvenance
from app.risk import RiskEngine, RiskLimits
from app.strategies.reference import strategy_from_spec
from scripts.phase2_common import load_json, parse_timestamp, strategy_for_asset
from scripts.phase3_common import revision


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--database-url", default="sqlite:///./data/trading_lab.db")
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/snapshots"))
    arguments = parser.parse_args()
    config = load_json(arguments.config)
    start = parse_timestamp(str(config["start_timestamp"]))
    if start < datetime.now(UTC) - timedelta(minutes=5):
        raise ValueError("genuine forward trial start cannot be backdated")
    dataset_id = str(config["warmup_dataset_id"])
    snapshot_store = DatasetSnapshotStore(arguments.snapshot_root)
    snapshot = snapshot_store.load_manifest(dataset_id)
    assets = {item.asset.symbol: item.asset for item in snapshot.instruments}
    provider_metadata = YahooReadOnlyProvider().provider_metadata()
    risk_policy = ForwardRiskPolicy(
        version=str(config.get("risk_policy_version", "phase3-paper-risk-v1")),
        limits=RiskLimits(stale_after=timedelta(hours=36)),
        maximum_strategy_allocation=float(config.get("maximum_strategy_allocation", 0.25)),
    )
    data_policy = ForwardDataPolicy(
        provider_name=provider_metadata.name,
        provider_version=provider_metadata.version,
        interval="1d",
        adjustment_policy=snapshot.adjustment_policy.value,
        corporate_action_policy=snapshot.corporate_action_policy,
        maximum_staleness=timedelta(hours=36),
        warmup_dataset_id=dataset_id,
        version=str(config.get("data_policy_version", "phase3-current-data-v1")),
    )
    manifests: list[ForwardTrialManifest] = []
    for raw in config.get("trials", []):
        item = _mapping(raw, "trial")
        symbol = str(item["symbol"])
        asset = assets[symbol]
        strategy = strategy_for_asset(asset, int(item.get("family_index", 0)))
        custom_parameters = item.get("parameters")
        if custom_parameters is not None:
            parameters = {
                **dict(strategy.spec.parameters),
                **_mapping(custom_parameters, "parameters"),
            }
            strategy = strategy_from_spec(
                strategy.spec.derive(
                    parameters=parameters,
                    reason="explicit frozen Phase 3 owner configuration",
                )
            )
        manifest = ForwardTrialManifest.create(
            portfolio_id=str(config["portfolio_id"]),
            strategy=strategy.spec,
            assets=(asset,),
            universe_version=f"{dataset_id}:forward-universe-v1",
            benchmark=ForwardBenchmarkDefinition(
                benchmark_id=f"{symbol}-buy-and-hold-v1",
                symbols=(str(item.get("benchmark_symbol", symbol)),),
            ),
            portfolio_starting_capital=float(config.get("starting_capital", 300_000.0)),
            allocation_weight=float(item["allocation_weight"]),
            costs=CostAssumptions.model_validate(config.get("costs", {})),
            risk_policy=risk_policy,
            data_policy=data_policy,
            start_timestamp=start,
            qualification_policy=ForwardQualificationPolicy.model_validate(
                config.get("qualification_policy", {})
            ),
            degradation_policy=ForwardDegradationPolicy.model_validate(
                config.get("degradation_policy", {})
            ),
            baseline_profile=ForwardBaselineProfile.model_validate(
                item.get("baseline_profile", {})
            ),
            code_revision=revision(),
            provenance=ObservationProvenance.GENUINE_FORWARD,
            random_seed=int(config.get("random_seed", 1729)),
        )
        manifests.append(manifest)
    if not manifests:
        raise ValueError("owner configuration contains no forward trials")
    database_engine = create_database_engine(arguments.database_url)
    Base.metadata.create_all(database_engine)
    repository = ForwardRepository(session_factory(database_engine))
    trials = tuple(repository.create_trial(item) for item in manifests)
    ForwardCycleOrchestrator(
        repository, ForwardPortfolioEngine(RiskEngine(risk_policy.limits))
    ).ensure_portfolio(trials)
    print(
        json.dumps(
            {
                "created": [item.manifest.trial_id for item in trials],
                "portfolio_id": config["portfolio_id"],
                "provenance": ObservationProvenance.GENUINE_FORWARD.value,
                "start_timestamp": start.isoformat(),
                "mode": "PAPER",
                "external_order_transmission": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
