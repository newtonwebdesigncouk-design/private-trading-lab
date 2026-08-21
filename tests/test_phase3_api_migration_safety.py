"""Phase 3 GET-only API, migration, configuration, and physical safety gates."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect

from app.api.main import create_app
from app.config.phase3 import ForwardProviderConfiguration
from app.models.enums import TradingMode
from scripts.check_no_live_execution import provider_findings, scan


def test_phase3_api_routes_are_get_only_and_replay_is_never_labelled_forward() -> None:
    application = create_app()
    client = TestClient(application)
    paths = (
        "/forward/trials",
        "/forward/portfolio",
        "/forward/performance",
        "/forward/health",
        "/forward/cycles",
        "/forward/data-quality",
    )
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json()["provenance"] == "REPLAY"
        assert response.json()["genuine_forward_trials_started"] == 0
    trials = client.get("/forward/trials").json()
    assert trials["available"] is True
    assert trials["items"]
    detail = client.get(f"/forward/trials/{trials['items'][0]['trial_id']}")
    assert detail.status_code == 200
    assert detail.json()["provenance"] == "REPLAY"
    assert client.get("/forward/trials/not-found").status_code == 404
    for route in application.routes:
        if getattr(route, "path", "").startswith("/forward"):
            assert getattr(route, "methods", set()) <= {"GET"}


def test_phase3_migration_creates_complete_forward_audit_schema(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    configuration = Config("alembic.ini")
    configuration.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(configuration, "head")
    tables = set(inspect(create_engine(f"sqlite:///{database.as_posix()}")).get_table_names())
    assert {
        "forward_trials",
        "forward_evidence_manifests",
        "forward_cycle_leases",
        "forward_cycles",
        "forward_observations",
        "forward_signals",
        "forward_orders",
        "forward_fills",
        "forward_benchmark_snapshots",
        "forward_portfolios",
        "forward_portfolio_snapshots",
        "forward_lifecycle_decisions",
        "forward_data_quality_events",
        "forward_degradation_events",
        "forward_audit_events",
    } <= tables
    command.downgrade(configuration, "0002_phase_2")
    remaining = set(inspect(create_engine(f"sqlite:///{database.as_posix()}")).get_table_names())
    assert not any(name.startswith("forward_") for name in remaining)


def test_phase3_configuration_and_scanner_reject_execution_credentials_and_writes(
    tmp_path: Path,
) -> None:
    assert {mode.value for mode in TradingMode} == {"BACKTEST", "PAPER"}
    assert provider_findings() == []
    with pytest.raises(ValidationError, match="credential-free/read-only"):
        ForwardProviderConfiguration(read_only=False)
    with pytest.raises(ValidationError, match="credential-free/read-only"):
        ForwardProviderConfiguration(requires_secret=True)

    root = tmp_path / "unsafe" / "app"
    root.mkdir(parents=True)
    (root / "bad.py").write_text(
        "broker_api_key: str = 'forbidden'\ndef submit_order() -> None:\n    return None\n",
        encoding="utf-8",
    )
    findings = scan(root)
    assert any("credential" in item for item in findings)
    assert any("forbidden callable" in item for item in findings)

    api_root = tmp_path / "api" / "app"
    api_root.mkdir(parents=True)
    (api_root / "bad_route.py").write_text(
        "class App:\n"
        "    def post(self, path: str): ...\n"
        "application = App()\n"
        "@application.post('/forward/unsafe')\n"
        "def unsafe() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    assert any("GET-only" in item for item in scan(api_root))
