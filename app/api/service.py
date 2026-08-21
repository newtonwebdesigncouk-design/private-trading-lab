"""Read model used by the local API and dashboard clients."""

from collections import Counter
from datetime import UTC, datetime

from app.backtesting import BacktestConfig, BacktestEngine
from app.data.synthetic import SyntheticMarketDataProvider
from app.models.enums import AssetClass, StrategyState, TradingMode
from app.scoring import StrategyScore, score_strategy
from app.strategies.reference import reference_strategies


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


service = LaboratoryService()
