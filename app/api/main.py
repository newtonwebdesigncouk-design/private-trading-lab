"""FastAPI endpoints for a small local dashboard."""

from fastapi import FastAPI, HTTPException

from app.api.service import service
from app.models.enums import TradingMode


def create_app() -> FastAPI:
    application = FastAPI(
        title="Private Trading Laboratory",
        version="0.1.0",
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

    return application


app = create_app()
