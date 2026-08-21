"""Read model used by the local API and dashboard clients."""

from collections import Counter
from datetime import UTC, datetime

from app.backtesting import BacktestConfig, BacktestEngine
from app.data.providers import StooqReadOnlyProvider, YahooReadOnlyProvider
from app.data.synthetic import SyntheticMarketDataProvider
from app.models.enums import AssetClass, StrategyState, TradingMode
from app.scoring import StrategyScore, score_strategy
from app.strategies.reference import reference_strategies
from app.validation.regimes import classify_regimes


class LaboratoryService:
    def __init__(self) -> None:
        provider = SyntheticMarketDataProvider(seed=1729)
        asset = next(
            asset for asset in provider.supported_assets() if asset.asset_class is AssetClass.EQUITY
        )
        bars = provider.historical_data(
            asset,
            datetime(2022, 1, 1, tzinfo=UTC),
            datetime(2024, 12, 31, 23, 59, tzinfo=UTC),
        )
        self.bars = bars
        self.providers = (
            provider.provider_metadata(),
            YahooReadOnlyProvider().provider_metadata(),
            StooqReadOnlyProvider().provider_metadata(),
        )
        engine = BacktestEngine(BacktestConfig())
        self.results = tuple(
            engine.run(strategy, bars, dataset_id="synthetic-v2:seed-1729:2022-2024")
            for strategy in reference_strategies(asset.symbol)
        )
        self.scores: dict[str, StrategyScore] = {
            result.strategy.version_key: score_strategy(result) for result in self.results
        }

    def portfolio_summary(self) -> dict[str, object]:
        best = max(self.results, key=lambda result: self.scores[result.strategy.version_key].score)
        return {
            "mode": TradingMode.PAPER,
            "starting_capital": best.starting_capital,
            "current_simulated_equity": best.final_equity,
            "cash": best.equity_curve[-1].cash,
            "positions": int(best.equity_curve[-1].position_quantity > 0),
            "drawdown": best.metrics.maximum_drawdown,
            "performance": best.metrics.total_return,
            "note": "Demonstration simulation; no external order capability exists.",
        }

    def strategy_summary(self) -> dict[str, int]:
        states = Counter(score.state for score in self.scores.values())
        return {
            "total_strategies_created": len(self.results),
            **{state.value.lower(): states[state] for state in StrategyState},
        }

    def data_health(self) -> dict[str, object]:
        return {
            "providers": [provider.model_dump(mode="json") for provider in self.providers],
            "dataset_snapshots": [],
            "freshness": {"demonstration_dataset": self.bars[-1].timestamp},
            "validation_warnings": [],
            "missing_data": {},
            "note": "Persistent manifests appear here when an owner snapshot store is configured.",
        }

    def research_batches(self) -> dict[str, object]:
        return {
            "items": [],
            "candidate_count": 0,
            "retained_count": 0,
            "rejected_count": 0,
            "multiple_testing_diagnostics": [],
            "holdout_locked": True,
        }

    def regime_summary(self) -> dict[str, object]:
        observations = classify_regimes(self.bars)
        return {
            "calculation_version": observations[0].calculation_version if observations else None,
            "items": [item.model_dump(mode="json") for item in observations[-20:]],
        }

    def portfolio_read_model(self) -> dict[str, object]:
        best = max(self.results, key=lambda result: self.scores[result.strategy.version_key].score)
        final = best.equity_curve[-1]
        return {
            "holdings": (
                [{"symbol": best.strategy.permitted_assets[0], "quantity": final.position_quantity}]
                if final.position_quantity
                else []
            ),
            "cash": final.cash,
            "equity_curve": [point.model_dump(mode="json") for point in best.equity_curve[-100:]],
            "drawdown": best.metrics.maximum_drawdown,
            "exposure": {"invested": best.metrics.exposure, "cash": 1 - best.metrics.exposure},
            "attribution": {"strategy": best.strategy.version_key},
            "benchmark_comparison": best.benchmark.model_dump(mode="json"),
        }

    def paper_read_model(self) -> dict[str, object]:
        return {
            "accounts": [],
            "last_cycle": None,
            "next_expected_cycle": None,
            "orders": [],
            "fills": [],
            "audit_events": [],
            "kill_switch_engaged": False,
            "external_order_transmission": False,
        }


service = LaboratoryService()
