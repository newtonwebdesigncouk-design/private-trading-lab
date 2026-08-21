"""Phase 2 read models, catalogue persistence, configuration, and safety scanning."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.main import create_app
from app.config.phase2 import Phase2Configuration
from app.data.snapshots import DatasetSnapshotStore
from app.data.synthetic import SyntheticMarketDataProvider
from app.database import (
    Base,
    ExperimentQuery,
    LaboratoryRepository,
    create_database_engine,
    session_factory,
)
from app.models.enums import AssetClass
from app.research import Phase2BatchResearchEngine
from app.research.experiments import ExperimentRecord
from app.strategies.reference import reference_strategies
from app.universe import UniverseDefinition, UniverseInstrument
from app.validation.regimes import classify_regimes
from scripts.check_no_live_execution import scan


def test_phase2_api_is_read_only_and_exposes_required_read_models() -> None:
    application = create_app()
    client = TestClient(application)
    paths = (
        "/data/providers",
        "/data/datasets",
        "/data/health",
        "/research/batches",
        "/research/regimes",
        "/portfolio/holdings",
        "/portfolio/equity-curve",
        "/portfolio/exposure",
        "/portfolio/attribution",
        "/portfolio/benchmarks",
        "/paper/accounts",
        "/paper/cycles",
        "/paper/orders",
        "/paper/fills",
        "/paper/audit",
    )
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
    providers = client.get("/data/providers").json()["items"]
    assert any(item["name"] == "yahoo-chart-read-only" for item in providers)
    assert all(item["capabilities"]["read_only"] for item in providers)
    assert client.get("/paper/cycles").json()["kill_switch_engaged"] is False
    for route in application.routes:
        if getattr(route, "path", "").startswith(("/data", "/research", "/portfolio", "/paper")):
            assert getattr(route, "methods", set()) <= {"GET"}


def test_phase2_configuration_cannot_enable_a_writable_provider() -> None:
    configuration = Phase2Configuration()
    assert configuration.provider.read_only
    assert configuration.research.maximum_candidates == 500
    assert configuration.portfolio.risk_limits.minimum_cash_reserve > 0
    with pytest.raises(ValidationError, match="read-only"):
        Phase2Configuration(provider={"read_only": False})  # type: ignore[arg-type]


def test_safety_scanner_allows_only_get_networking_inside_provider_boundary(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed" / "app"
    provider = allowed_root / "data" / "providers" / "safe.py"
    provider.parent.mkdir(parents=True)
    provider.write_text(
        "from urllib.request import Request\n"
        "def fetch(url: str) -> object:\n"
        "    return Request(url, method='GET')\n",
        encoding="utf-8",
    )
    assert scan(allowed_root) == []

    outside_root = tmp_path / "outside" / "app"
    outside_root.mkdir(parents=True)
    (outside_root / "bad.py").write_text("import urllib.request\n", encoding="utf-8")
    assert any("outside approved" in item for item in scan(outside_root))

    write_root = tmp_path / "write" / "app"
    bad_provider = write_root / "data" / "providers" / "bad.py"
    bad_provider.parent.mkdir(parents=True)
    bad_provider.write_text(
        "from urllib.request import Request\n"
        "def fetch(url: str) -> object:\n"
        "    return Request(url, method='POST')\n",
        encoding="utf-8",
    )
    assert any("write method" in item for item in scan(write_root))


def test_phase2_catalogue_persists_immutable_artifacts_and_queries(tmp_path: Path) -> None:
    database_engine = create_database_engine(f"sqlite:///{tmp_path / 'catalogue.db'}")
    Base.metadata.create_all(database_engine)
    repository = LaboratoryRepository(session_factory(database_engine))
    provider = SyntheticMarketDataProvider(seed=55)
    asset = next(
        item for item in provider.supported_assets() if item.asset_class is AssetClass.EQUITY
    )
    start = datetime(2022, 1, 1, tzinfo=UTC)
    end = datetime(2022, 8, 1, tzinfo=UTC)
    batch = provider.historical_batch(asset, start, end)
    snapshot_store = DatasetSnapshotStore(tmp_path / "snapshots")
    manifest = snapshot_store.freeze(
        "catalogue",
        (batch,),
        code_revision="test-commit",
        corporate_action_policy="synthetic cash dividends",
    )
    repository.save_dataset_manifest(manifest, snapshot_store.root / manifest.dataset_id)
    with pytest.raises(ValueError, match="immutable"):
        repository.save_dataset_manifest(manifest, snapshot_store.root / manifest.dataset_id)
    universe = UniverseDefinition(
        universe_id="catalogue",
        version=1,
        provider=provider.name,
        instruments=(
            UniverseInstrument(
                asset=asset,
                category="test",
                inclusion_reason="catalogue persistence fixture",
            ),
        ),
    )
    repository.save_universe(universe)
    with pytest.raises(ValueError, match="immutable"):
        repository.save_universe(universe)
    parent = reference_strategies(asset.symbol)[0].spec
    research = Phase2BatchResearchEngine(maximum_candidates=1).run_selection(
        parent,
        {"fast_window": (10,)},
        {asset.symbol: batch.bars},
        dataset_id=manifest.dataset_id,
        universe_version=universe.version_key,
        random_seed=1,
        retention_score=0,
        minimum_validation_trades=0,
        false_discovery_rate=0.99,
    )
    repository.save_research_batch(research)
    with pytest.raises(ValueError, match="immutable"):
        repository.save_research_batch(research)
    regimes = classify_regimes(batch.bars, lookback=10)
    repository.save_regime_labels(manifest.dataset_id, asset.symbol, regimes[:3])

    experiment = ExperimentRecord(
        experiment_id="phase2-query-v1",
        strategy_version=parent.version_key,
        dataset_version=manifest.dataset_id,
        instruments=(asset.symbol,),
        period_start=batch.bars[0].timestamp,
        period_end=batch.bars[-1].timestamp,
        transaction_cost_assumptions={"commission_bps": 2.0},
        parameters=dict(parent.parameters),
        code_version="test-commit",
        random_seed=1,
        metrics={"return": 0.1},
        validation_result="VALIDATION",
        universe_version=universe.version_key,
        regime="BULLISH/LOW",
        lifecycle_state="VALIDATION",
        score=72,
        benchmark_outcome="UNDERPERFORMED",
        candidate_count=research.candidate_count,
    )
    repository.save_experiment(experiment)
    query = ExperimentQuery(
        dataset_version=manifest.dataset_id,
        universe_version=universe.version_key,
        instrument=asset.symbol,
        regime="BULLISH/LOW",
        lifecycle_state="VALIDATION",
        minimum_score=70,
        maximum_score=80,
        benchmark_outcome="UNDERPERFORMED",
    )
    assert repository.search_experiments(query) == (experiment,)
    assert repository.recent_experiments(1) == (experiment,)
