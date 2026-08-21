"""Critical version-1 safety boundary tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.models.enums import StrategyState, TradingMode
from app.paper_trading import PaperTradingEngine
from scripts.check_no_live_execution import scan


def test_only_simulation_modes_are_representable() -> None:
    assert {mode.value for mode in TradingMode} == {"BACKTEST", "PAPER"}


def test_live_mode_cannot_be_configured() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, trading_mode="LIVE")  # type: ignore[arg-type,call-arg]


def test_unknown_credential_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, broker_api_key="secret")  # type: ignore[call-arg]


def test_strategy_lifecycle_has_no_live_state() -> None:
    assert "LIVE" not in {state.value for state in StrategyState}


def test_paper_engine_has_no_external_submission_method() -> None:
    method_names = set(dir(PaperTradingEngine))
    assert "submit_order" not in method_names
    assert "transmit_order" not in method_names
    assert PaperTradingEngine.mode is TradingMode.PAPER


def test_repository_safety_scan_passes() -> None:
    assert scan(Path("app")) == []
