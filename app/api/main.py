"""FastAPI endpoints for a small local dashboard."""

from fastapi import FastAPI, HTTPException

from app.api.service import service
from app.models.enums import TradingMode


def create_app() -> FastAPI:
    application = FastAPI(
        title="Private Trading Laboratory",
        version="0.2.0",
        description="Private simulation-only strategy research API",
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "execution": "simulation-only"}

    @application.get("/safety")
    def safety() -> dict[str, object]:
        return {
            "supported_modes": [mode.value for mode in TradingMode],
            "external_order_transmission": False,
            "broker_credentials_required": False,
        }

    @application.get("/portfolio")
    def portfolio() -> dict[str, object]:
        return service.portfolio_summary()

    @application.get("/strategies")
    def strategies() -> dict[str, object]:
        return {
            "summary": service.strategy_summary(),
            "items": [
                {
                    "version": result.strategy.version_key,
                    "name": result.strategy.name,
                    "state": service.scores[result.strategy.version_key].state,
                    "score": service.scores[result.strategy.version_key].score,
                }
                for result in service.results
            ],
        }

    @application.get("/strategies/{version_key}")
    def strategy_detail(version_key: str) -> dict[str, object]:
        result = next(
            (item for item in service.results if item.strategy.version_key == version_key), None
        )
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

    @application.get("/research/experiments")
    def experiments() -> dict[str, object]:
        return {
            "items": [
                {
                    "strategy_version": result.strategy.version_key,
                    "dataset": result.dataset_id,
                    "outcome": service.scores[result.strategy.version_key].state,
                    "reasons": service.scores[result.strategy.version_key].reasons,
                }
                for result in service.results
            ]
        }

    @application.get("/data/providers")
    def data_providers() -> dict[str, object]:
        health = service.data_health()
        return {"items": health["providers"]}

    @application.get("/data/datasets")
    def datasets() -> dict[str, object]:
        health = service.data_health()
        return {"items": health["dataset_snapshots"]}

    @application.get("/data/health")
    def data_health() -> dict[str, object]:
        return service.data_health()

    @application.get("/research/batches")
    def research_batches() -> dict[str, object]:
        return service.research_batches()

    @application.get("/research/regimes")
    def research_regimes() -> dict[str, object]:
        return service.regime_summary()

    @application.get("/portfolio/holdings")
    def portfolio_holdings() -> dict[str, object]:
        return {"items": service.portfolio_read_model()["holdings"]}

    @application.get("/portfolio/equity-curve")
    def portfolio_equity_curve() -> dict[str, object]:
        return {"items": service.portfolio_read_model()["equity_curve"]}

    @application.get("/portfolio/exposure")
    def portfolio_exposure() -> dict[str, object]:
        model = service.portfolio_read_model()
        return {"cash": model["cash"], "exposure": model["exposure"]}

    @application.get("/portfolio/attribution")
    def portfolio_attribution() -> dict[str, object]:
        return {"items": service.portfolio_read_model()["attribution"]}

    @application.get("/portfolio/benchmarks")
    def portfolio_benchmarks() -> dict[str, object]:
        return {"items": service.portfolio_read_model()["benchmark_comparison"]}

    @application.get("/paper/accounts")
    def paper_accounts() -> dict[str, object]:
        return {"items": service.paper_read_model()["accounts"]}

    @application.get("/paper/cycles")
    def paper_cycles() -> dict[str, object]:
        model = service.paper_read_model()
        return {
            "last_cycle": model["last_cycle"],
            "next_expected_cycle": model["next_expected_cycle"],
            "kill_switch_engaged": model["kill_switch_engaged"],
        }

    @application.get("/paper/orders")
    def paper_orders() -> dict[str, object]:
        return {"items": service.paper_read_model()["orders"]}

    @application.get("/paper/fills")
    def paper_fills() -> dict[str, object]:
        return {"items": service.paper_read_model()["fills"]}

    @application.get("/paper/audit")
    def paper_audit() -> dict[str, object]:
        return {"items": service.paper_read_model()["audit_events"]}

    return application


app = create_app()
