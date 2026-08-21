"""FastAPI endpoints for a small private dashboard."""

from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.api.service import service
from app.backtesting.models import BacktestResult
from app.config import get_settings
from app.models.enums import TradingMode

bearer_scheme = HTTPBearer(auto_error=False)


class BacktestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_version: str = Field(min_length=1)
    starting_capital: float = Field(default=100_000.0, gt=0, le=10_000_000)


def backtest_payload(result: BacktestResult) -> dict[str, object]:
    return result.model_dump(mode="json")


def require_dashboard_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Require the shared dashboard token when one is configured."""

    configured = get_settings().trading_lab_api_token
    if configured is None:
        return
    supplied = credentials.credentials if credentials is not None else ""
    if not compare_digest(supplied, configured.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="dashboard authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_app() -> FastAPI:
    application = FastAPI(
        title="Private Trading Laboratory",
        version="0.3.0",
        description="Private simulation-only strategy research API",
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "execution": "simulation-only"}

    protected = [Depends(require_dashboard_token)]

    @application.get("/system/health", dependencies=protected)
    def system_health() -> dict[str, object]:
        return {
            "status": "ok",
            "execution": "simulation-only",
            "supported_modes": [mode.value for mode in TradingMode],
            "external_order_transmission": False,
            "strategy_count": len(service.results),
            "experiment_count": len(service.results),
            "dataset": service.active_dataset_id(),
        }

    @application.get("/safety", dependencies=protected)
    def safety() -> dict[str, object]:
        return {
            "supported_modes": [mode.value for mode in TradingMode],
            "external_order_transmission": False,
            "broker_credentials_required": False,
        }

    @application.get("/portfolio", dependencies=protected)
    def portfolio() -> dict[str, object]:
        return service.portfolio_summary()

    @application.get("/strategies", dependencies=protected)
    def strategies() -> dict[str, object]:
        return {
            "summary": service.strategy_summary(),
            "items": [
                {
                    "version": result.strategy.version_key,
                    "name": result.strategy.name,
                    "state": service.scores[result.strategy.version_key].state,
                    "score": service.scores[result.strategy.version_key].score,
                    "score_components": service.scores[result.strategy.version_key].components,
                    "score_reasons": service.scores[result.strategy.version_key].reasons,
                    "asset_class": result.strategy.asset_class,
                    "permitted_assets": result.strategy.permitted_assets,
                    "timeframe": result.strategy.timeframe,
                    "created_at": result.strategy.created_at,
                    "parent_strategy": result.strategy.parent_strategy,
                    "description": result.strategy.description,
                    "parameters": dict(result.strategy.parameters),
                    "entry_conditions": result.strategy.entry_conditions,
                    "exit_conditions": result.strategy.exit_conditions,
                    "stop_conditions": result.strategy.stop_conditions,
                    "metrics": result.metrics,
                    "benchmark": result.benchmark,
                }
                for result in service.results
            ],
        }

    @application.get("/strategies/{version_key}", dependencies=protected)
    def strategy_detail(version_key: str) -> dict[str, object]:
        result = service.result_for(version_key)
        if result is None:
            raise HTTPException(status_code=404, detail="strategy version not found")
        return {
            "strategy": result.strategy,
            "score": service.scores[version_key],
            "metrics": result.metrics,
            "benchmark": result.benchmark,
            "costs": result.costs,
            "trades": result.trades,
            "equity_curve": result.equity_curve,
            "validation": {"state": service.scores[version_key].state},
        }

    @application.get("/backtests", dependencies=protected)
    def backtests() -> dict[str, object]:
        return {
            "items": [
                {
                    "strategy_version": result.strategy.version_key,
                    "strategy_name": result.strategy.name,
                    "dataset": result.dataset_id,
                    "start": result.start,
                    "end": result.end,
                    "starting_capital": result.starting_capital,
                    "final_equity": result.final_equity,
                    "metrics": result.metrics,
                    "benchmark": result.benchmark,
                    "costs": result.costs,
                }
                for result in service.results
            ]
        }

    @application.post("/backtests/run", dependencies=protected)
    def run_backtest(request: BacktestRunRequest) -> dict[str, object]:
        result = service.run_reference_backtest(
            request.strategy_version,
            starting_capital=request.starting_capital,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="strategy version not found")
        return backtest_payload(result)

    @application.get("/research/experiments", dependencies=protected)
    def experiments() -> dict[str, object]:
        return {
            "items": [
                {
                    "experiment_id": f"phase1-{index:04d}",
                    "strategy_version": result.strategy.version_key,
                    "strategy_name": result.strategy.name,
                    "dataset": result.dataset_id,
                    "period_start": result.start,
                    "period_end": result.end,
                    "parameters": dict(result.strategy.parameters),
                    "random_seed": 1729,
                    "code_revision": "phase1-reference",
                    "outcome": service.scores[result.strategy.version_key].state,
                    "score": service.scores[result.strategy.version_key].score,
                    "metrics": result.metrics,
                    "reasons": service.scores[result.strategy.version_key].reasons,
                }
                for index, result in enumerate(service.results, start=1)
            ]
        }

    @application.get("/phase2/demo", dependencies=protected)
    def phase2_demo() -> dict[str, object]:
        return service.phase2_demo_summary()

    @application.get("/data/providers", dependencies=protected)
    def data_providers() -> dict[str, object]:
        health = service.data_health()
        return {"items": health["providers"]}

    @application.get("/data/datasets", dependencies=protected)
    def datasets() -> dict[str, object]:
        health = service.data_health()
        return {"items": health["dataset_snapshots"]}

    @application.get("/data/health", dependencies=protected)
    def data_health() -> dict[str, object]:
        return service.data_health()

    @application.get("/research/batches", dependencies=protected)
    def research_batches() -> dict[str, object]:
        return service.research_batches()

    @application.get("/research/regimes", dependencies=protected)
    def research_regimes() -> dict[str, object]:
        return service.regime_summary()

    @application.get("/portfolio/holdings", dependencies=protected)
    def portfolio_holdings() -> dict[str, object]:
        return {"items": service.portfolio_read_model()["holdings"]}

    @application.get("/portfolio/equity-curve", dependencies=protected)
    def portfolio_equity_curve() -> dict[str, object]:
        return {"items": service.portfolio_read_model()["equity_curve"]}

    @application.get("/portfolio/exposure", dependencies=protected)
    def portfolio_exposure() -> dict[str, object]:
        model = service.portfolio_read_model()
        return {"cash": model["cash"], "exposure": model["exposure"]}

    @application.get("/portfolio/attribution", dependencies=protected)
    def portfolio_attribution() -> dict[str, object]:
        return {"items": service.portfolio_read_model()["attribution"]}

    @application.get("/portfolio/benchmarks", dependencies=protected)
    def portfolio_benchmarks() -> dict[str, object]:
        return {"items": service.portfolio_read_model()["benchmark_comparison"]}

    @application.get("/paper/accounts", dependencies=protected)
    def paper_accounts() -> dict[str, object]:
        return {"items": service.paper_read_model()["accounts"]}

    @application.get("/paper/cycles", dependencies=protected)
    def paper_cycles() -> dict[str, object]:
        model = service.paper_read_model()
        return {
            "last_cycle": model["last_cycle"],
            "next_expected_cycle": model["next_expected_cycle"],
            "kill_switch_engaged": model["kill_switch_engaged"],
        }

    @application.get("/paper/orders", dependencies=protected)
    def paper_orders() -> dict[str, object]:
        return {"items": service.paper_read_model()["orders"]}

    @application.get("/paper/fills", dependencies=protected)
    def paper_fills() -> dict[str, object]:
        return {"items": service.paper_read_model()["fills"]}

    @application.get("/paper/audit", dependencies=protected)
    def paper_audit() -> dict[str, object]:
        return {"items": service.paper_read_model()["audit_events"]}

    @application.get("/forward/trials", dependencies=protected)
    def forward_trials() -> dict[str, object]:
        return service.phase3_forward_read_model("trials")

    @application.get("/forward/trials/{trial_id}", dependencies=protected)
    def forward_trial_detail(trial_id: str) -> dict[str, object]:
        detail = service.phase3_trial_detail(trial_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="forward trial not found")
        return detail

    @application.get("/forward/portfolio", dependencies=protected)
    def forward_portfolio() -> dict[str, object]:
        return service.phase3_forward_read_model("portfolio")

    @application.get("/forward/performance", dependencies=protected)
    def forward_performance() -> dict[str, object]:
        return service.phase3_forward_read_model("performance")

    @application.get("/forward/health", dependencies=protected)
    def forward_health() -> dict[str, object]:
        return service.phase3_forward_read_model("health")

    @application.get("/forward/cycles", dependencies=protected)
    def forward_cycles() -> dict[str, object]:
        return service.phase3_forward_read_model("cycles")

    @application.get("/forward/data-quality", dependencies=protected)
    def forward_data_quality() -> dict[str, object]:
        return service.phase3_forward_read_model("data_quality")

    return application


app = create_app()
