"""Persistence, migration, API and milestone command integration tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.api.main import app, create_app
from app.backtesting import BacktestEngine
from app.config import get_settings
from app.data.synthetic import SyntheticMarketDataProvider
from app.database import Base, LaboratoryRepository, create_database_engine, session_factory
from app.models.enums import AssetClass
from app.research.experiments import ExperimentRecord
from app.strategies.reference import reference_strategies
from scripts.run_backtest import run


def test_repository_persists_immutable_strategy_result_experiment_and_audit(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'lab.db').as_posix()}")
    Base.metadata.create_all(engine)
    repository = LaboratoryRepository(session_factory(engine))
    provider = SyntheticMarketDataProvider(seed=7)
    asset = next(
        item for item in provider.supported_assets() if item.asset_class is AssetClass.EQUITY
    )
    bars = provider.historical_data(
        asset,
        datetime(2022, 1, 1, tzinfo=UTC),
        datetime(2022, 12, 31, 23, 59, tzinfo=UTC),
    )
    strategy = reference_strategies(asset.symbol)[0]
    result = BacktestEngine().run(strategy, bars, dataset_id="persisted-dataset")
    repository.save_strategy(strategy.spec)
    with pytest.raises(ValueError, match="immutable"):
        repository.save_strategy(strategy.spec)
    result_id = repository.save_backtest(result)
    assert len(result_id) == 64

    experiment = ExperimentRecord(
        experiment_id="exp-1",
        strategy_version=strategy.spec.version_key,
        dataset_version=result.dataset_id,
        instruments=(asset.symbol,),
        period_start=result.start,
        period_end=result.end,
        transaction_cost_assumptions=result.costs.model_dump(),
        parameters=dict(strategy.spec.parameters),
        code_version="test-revision",
        random_seed=7,
        metrics=result.metrics.model_dump(mode="json"),
        validation_result="OUT_OF_SAMPLE_PENDING",
        rejection_reason="requires more instruments",
    )
    repository.save_experiment(experiment)
    repository.record("TEST_AUDIT", {"safe": True}, datetime.now(UTC))
    assert repository.recent_experiments() == (experiment,)


@pytest.mark.integration
def test_alembic_migration_builds_expected_schema(tmp_path: Path) -> None:
    database_path = (tmp_path / "migration.db").as_posix()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite:///{database_path}")
    tables = set(inspect(engine).get_table_names())
    assert {
        "strategies",
        "backtest_results",
        "experiments",
        "paper_audit_events",
        "alembic_version",
    } <= tables


def test_local_api_exposes_safety_portfolio_strategies_and_research() -> None:
    client = TestClient(app)
    safety = client.get("/safety")
    assert safety.status_code == 200
    assert safety.json() == {
        "supported_modes": ["BACKTEST", "PAPER"],
        "external_order_transmission": False,
        "broker_credentials_required": False,
    }
    portfolio = client.get("/portfolio")
    assert portfolio.status_code == 200
    assert "current_simulated_equity" in portfolio.json()
    strategies = client.get("/strategies").json()
    assert strategies["summary"]["total_strategies_created"] == 4
    assert {
        "metrics",
        "benchmark",
        "asset_class",
        "timeframe",
        "parameters",
        "entry_conditions",
        "exit_conditions",
    } <= strategies["items"][0].keys()
    version = strategies["items"][0]["version"]
    detail = client.get(f"/strategies/{version}")
    assert detail.status_code == 200
    assert {"metrics", "benchmark", "costs", "trades", "equity_curve"} <= detail.json().keys()
    system_health = client.get("/system/health")
    assert system_health.status_code == 200
    assert system_health.json()["external_order_transmission"] is False
    assert system_health.json()["supported_modes"] == ["BACKTEST", "PAPER"]
    backtests = client.get("/backtests")
    assert backtests.status_code == 200
    assert len(backtests.json()["items"]) == 4
    run = client.post(
        "/backtests/run",
        json={"strategy_version": version, "starting_capital": 125_000},
    )
    assert run.status_code == 200
    assert run.json()["starting_capital"] == 125_000
    assert run.json()["strategy"]["strategy_id"]
    experiments = client.get("/research/experiments")
    assert experiments.status_code == 200
    assert experiments.json()["items"][0]["random_seed"] == 1729
    assert experiments.json()["items"][0]["code_revision"] == "phase1-reference"
    assert client.get("/strategies/not-found:v1").status_code == 404
    assert (
        client.post(
            "/backtests/run",
            json={"strategy_version": "not-found:v1", "starting_capital": 100_000},
        ).status_code
        == 404
    )


def test_dashboard_token_protects_private_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_LAB_API_TOKEN", "test-dashboard-token")
    get_settings.cache_clear()
    protected_client = TestClient(create_app())
    try:
        assert protected_client.get("/health").status_code == 200
        for path in ("/strategies", "/data/providers", "/paper/cycles"):
            assert protected_client.get(path).status_code == 401
        assert (
            protected_client.get(
                "/strategies",
                headers={"Authorization": "Bearer wrong-token"},
            ).status_code
            == 401
        )
        assert (
            protected_client.get(
                "/strategies",
                headers={"Authorization": "Bearer test-dashboard-token"},
            ).status_code
            == 200
        )
        assert (
            protected_client.get(
                "/data/providers",
                headers={"Authorization": "Bearer test-dashboard-token"},
            ).status_code
            == 200
        )
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
def test_milestone_report_is_reproducible_and_explains_every_rank() -> None:
    first = run()
    second = run()
    assert first == second
    assert len(first["strategies"]) == 4
    assert [row["rank"] for row in first["strategies"]] == [1, 2, 3, 4]
    for row in first["strategies"]:
        assert row["disposition"] in {
            "PASSED FOR PAPER ELIGIBILITY",
            "FAILED",
            "REQUIRES FURTHER VALIDATION",
        }
        assert row["reasons"]
        assert row["costs"]["slippage_bps"] > 0
